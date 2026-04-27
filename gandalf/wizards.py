import logging
from copy import copy
from dataclasses import dataclass, replace
from http import HTTPStatus

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.views.generic.edit import FormView

from gandalf.storage import SessionStorage


logger = logging.getLogger(__name__)


class WizardNode:
    pass


@dataclass(frozen=True)
class Empty(WizardNode):
    pass


@dataclass(frozen=True)
class Sequence(WizardNode):
    children: tuple[WizardNode, ...]


@dataclass(frozen=True)
class Condition:
    predicate: object
    target: WizardNode


@dataclass(frozen=True)
class Branch(WizardNode):
    conditions: tuple[Condition, ...]
    default: WizardNode | None = None

    def configure(self, *, template_name=None):
        return replace(
            self,
            conditions=tuple(
                replace(
                    condition,
                    target=configure_node(
                        condition.target,
                        template_name=template_name,
                    ),
                )
                for condition in self.conditions
            ),
            default=configure_node(self.default, template_name=template_name),
        )

    def select(self, request):
        for condition in self.conditions:
            if condition.predicate(request):
                return condition.target

        return self.default


def condition(predicate, target):
    return Condition(predicate=predicate, target=target.root)


def form_view_factory(form_class, *, template_name):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        def get_success_url(self):
            return self.request.path

    GeneratedFormView.form_class = form_class
    GeneratedFormView.template_name = template_name
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView


@dataclass(frozen=True)
class Step(WizardNode):
    declaration: type
    form_view: type[FormView] | None = None

    def configure(self, *, template_name=None):
        if issubclass(self.declaration, forms.Form):
            if template_name is None:
                raise ImproperlyConfigured(
                    "Wizard.configure() must receive template_name when "
                    "generating FormView steps from Form classes."
                )

            return replace(
                self,
                form_view=form_view_factory(
                    self.declaration,
                    template_name=template_name,
                ),
            )

        return replace(self, form_view=self.declaration)


def configure_node(node, *, template_name=None):
    if node is None:
        return None

    if isinstance(node, Empty):
        return node

    if isinstance(node, Sequence):
        return replace(
            node,
            children=tuple(
                configure_node(child, template_name=template_name)
                for child in node.children
            ),
        )

    return node.configure(template_name=template_name)


def get_steps(node):
    if isinstance(node, Empty):
        return []

    if isinstance(node, Sequence):
        steps = []
        for child in node.children:
            steps.extend(get_steps(child))
        return steps

    if isinstance(node, Step):
        return [node]

    return []


class Wizard:
    def __init__(self, *, root=None):
        if root is None:
            root = Empty()

        self.root = root

    @property
    def steps(self):
        return get_steps(self.root)

    def step(self, form_class_or_form_view_class, context=None):
        return self._append(Step(declaration=form_class_or_form_view_class))

    def branch(self, *conditions, default=None):
        if default is not None:
            default = default.root

        return self._append(Branch(conditions=conditions, default=default))

    def _append(self, node):
        if isinstance(self.root, Empty):
            return self.__class__(root=Sequence(children=(node,)))

        if isinstance(self.root, Sequence):
            return self.__class__(
                root=replace(
                    self.root,
                    children=(
                        *self.root.children,
                        node,
                    ),
                ),
            )

        return self.__class__(root=Sequence(children=(self.root, node)))

    def configure(self, **configuration):
        return ConfiguredWizard(
            root=self.root,
            configuration=configuration,
        )


class ConfiguredWizard:
    storage_class = SessionStorage

    def __init__(self, *, root, configuration):
        self.configuration = configuration
        self.root = self._configure_root(root)
        self.storage_class = configuration.get("storage_class", self.storage_class)

    @property
    def steps(self):
        return get_steps(self.root)

    def configure(self, **configuration):
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def _configure_root(self, root):
        template_name = self.configuration.get("template_name")

        return configure_node(root, template_name=template_name)

    def get_bound_wizard(self, request):
        return BoundWizard(self, request, self.storage_class(request))


class BoundWizard:
    def __init__(self, wizard, request, storage):
        self.wizard = wizard
        self.request = request
        self.storage = storage
        self.run_id = None

    def initialise(self):
        self.run_id = self.storage.initialise_run()
        logger.debug("Initialise BoundWizard: %s", self.run_id)

    def retrieve(self, run_id):
        self.run_id = self.storage.retrieve_run(run_id)
        logger.debug("Retrieving BoundWizard: %s", self.run_id)

    def get_run_data(self):
        return self.storage.get_run_data(self.run_id)

    def get_submissions(self):
        return self.storage.get_submissions(self.run_id)

    def submit(self, submission, *args, **kwargs):
        self.storage.set_submissions(
            self.run_id,
            self._build_updated_submissions(
                submission,
                *args,
                **kwargs,
            ),
        )

    def _build_updated_submissions(self, submission, *args, **kwargs):
        updated_submissions = []
        stored_submissions = self.get_submissions()
        active_steps = self._get_active_steps(stored_submissions)

        for step, stored_submission in zip(active_steps, stored_submissions):
            response = self._dispatch_step(
                step,
                self._build_step_request("POST", submission=stored_submission),
                *args,
                **kwargs,
            )

            if self._response_satisfies_step(response):
                updated_submissions.append(stored_submission)
                continue

            updated_submissions.append(submission)
            return updated_submissions

        if len(updated_submissions) < len(active_steps):
            updated_submissions.append(submission)

        return updated_submissions

    def replay(self, *args, **kwargs):
        submissions = self.get_submissions()
        active_steps = self._get_active_steps(submissions)

        for step, submission in zip(active_steps, submissions):
            response = self._dispatch_step(
                step,
                self._build_step_request("POST", submission=submission),
                *args,
                **kwargs,
            )

            if not self._response_satisfies_step(response):
                return response

        remaining_steps = active_steps[len(submissions) :]
        if remaining_steps:
            return self._dispatch_step(
                remaining_steps[0],
                self._build_step_request("GET"),
                *args,
                **kwargs,
            )

        return None

    def _get_active_steps(self, submissions):
        steps, _ = self._get_active_steps_from_node(
            self.wizard.root,
            submissions=submissions,
            consumed_submission_count=0,
        )
        return steps

    def _get_active_steps_from_node(
        self,
        node,
        *,
        submissions,
        consumed_submission_count,
    ):
        if isinstance(node, Empty):
            return [], consumed_submission_count

        if isinstance(node, Step):
            return [node], consumed_submission_count + 1

        if isinstance(node, Sequence):
            steps = []
            for child in node.children:
                child_steps, consumed_submission_count = (
                    self._get_active_steps_from_node(
                        child,
                        submissions=submissions,
                        consumed_submission_count=consumed_submission_count,
                    )
                )
                steps.extend(child_steps)

                if consumed_submission_count > len(submissions):
                    break

            return steps, consumed_submission_count

        if isinstance(node, Branch):
            selected_node = node.select(self._build_step_request("GET"))
            if selected_node is None:
                return [], consumed_submission_count

            return self._get_active_steps_from_node(
                selected_node,
                submissions=submissions,
                consumed_submission_count=consumed_submission_count,
            )

        return [], consumed_submission_count

    def _response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def _dispatch_step(self, step, request, *args, **kwargs):
        step_view = step.form_view.as_view()
        return step_view(request, *args, **kwargs)

    def _build_step_request(self, method, submission=None):
        request = copy(self.request)
        request.method = method
        request.wizard = self

        if method == "POST":
            request.POST = submission

        return request
