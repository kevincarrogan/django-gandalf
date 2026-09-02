from django.urls import include, path

from . import views
from .from_formtools import djangogirls, squest, two_factor
from .readme import (
    ch01_first_wizard,
    ch02_branching,
    ch03_switch,
    ch04_expand,
    ch05_per_request,
    ch06_step_views,
    ch07_review,
    ch08_escapes,
    ch09_uploads,
    ch10_records,
    ch11_stash,
    ch12_task_list,
    ch13_budget,
    ch14_gated,
    ch15_journey,
)


urlpatterns = [
    path(
        "off-route-switch-wizard/",
        include(views.OffRouteSwitchWizardViewSet.urls()),
    ),
    path(
        "dynamic-summary-wizard/",
        include(views.DynamicSummaryWizardViewSet.urls()),
    ),
    path(
        "",
        views.IndexView.as_view(),
        name="index",
    ),
    # The README's worked example, chapter by chapter (tests/testapp/readme/,
    # driven by tests/functional/test_readme_examples.py).
    path("readme/first/", include(ch01_first_wizard.FirstApplicationViewSet.urls())),
    path(
        "readme/branching/", include(ch02_branching.BranchingApplicationViewSet.urls())
    ),
    path("readme/switch/", include(ch03_switch.SwitchingApplicationViewSet.urls())),
    path("readme/expand/", include(ch04_expand.ExpandingApplicationViewSet.urls())),
    path("readme/paper/", include(ch05_per_request.PaperApplicationViewSet.urls())),
    path("readme/staff/sign-in/", views.staff_sign_in, name="readme-staff-sign-in"),
    path("readme/staff/sign-out/", views.staff_sign_out, name="readme-staff-sign-out"),
    path(
        "readme/funds/<slug:fund>/",
        include(ch05_per_request.FundApplicationViewSet.urls()),
    ),
    path(
        "readme/step-view/", include(ch06_step_views.WebsiteApplicationViewSet.urls())
    ),
    path("readme/review/", include(ch07_review.ReviewedApplicationViewSet.urls())),
    path("readme/escape/", include(ch08_escapes.EscapingApplicationViewSet.urls())),
    path("readme/login/", ch08_escapes.login_placeholder, name="readme-login"),
    path("readme/upload/", include(ch09_uploads.DocumentedApplicationViewSet.urls())),
    path("readme/record/", include(ch10_records.RecordedApplicationViewSet.urls())),
    path(
        "readme/received/<int:pk>/",
        ch10_records.application_received,
        name="readme-received",
    ),
    path("readme/stash/", include(ch11_stash.ContactDetailsViewSet.urls())),
    path(
        "readme/stash-reopen/",
        ch11_stash.reopen_contact_details,
        name="readme-stash-reopen",
    ),
    # A task list owns every URL beneath it: its page, a door per entry, and
    # the entries themselves.
    path("readme/task-list/", include(ch12_task_list.GrantApplicationViewSet.urls())),
    path("readme/project/", include(ch13_budget.ProjectViewSet.urls())),
    path("readme/gated/", include(ch14_gated.GatedViewSet.urls())),
    # A journey: the setup wizard mints an id, and the whole application is
    # mounted under it. "new" is listed before the journey pattern so it is
    # never read as an id.
    path("readme/apply/new/", include(ch15_journey.ApplicationStartViewSet.urls())),
    path(
        "readme/apply/<slug:journey>/",
        include(ch15_journey.GrantApplicationViewSet.urls()),
    ),
    path(
        "path-aware-walked-past-wizard/",
        include(views.PathAwareWalkedPastWizardViewSet.urls()),
    ),
    path(
        "empty-path-first-step-wizard/",
        include(views.EmptyPathFirstStepWizardViewSet.urls()),
    ),
    path(
        "empty-path-branch-wizard/",
        include(views.EmptyPathBranchWizardViewSet.urls()),
    ),
    path("wizard/", include(views.SingleStepWizardViewSet.urls())),
    path("run-unavailable-wizard/", include(views.RunUnavailableWizardViewSet.urls())),
    path(
        "pruned-completion-wizard/",
        include(views.PrunedCompletionWizardViewSet.urls()),
    ),
    path(
        "wizard-without-done/", include(views.SingleStepWizardWithoutDoneViewSet.urls())
    ),
    path("wizard-done-data/", include(views.SingleStepWizardDoneDataViewSet.urls())),
    path(
        "wizard-done-run-data/",
        include(views.SingleStepWizardDoneRunDataViewSet.urls()),
    ),
    path(
        "run-metadata-wizard/",
        include(views.RunMetadataWizardViewSet.urls()),
    ),
    path(
        "one-time-token-wizard/",
        include(views.OneTimeTokenWizardViewSet.urls()),
    ),
    # Real formtools wizards, translated (tests/testapp/from_formtools/,
    # driven by tests/functional/test_from_formtools.py).
    path(
        "from-formtools/djangogirls/",
        include(djangogirls.OrganiseAnEventViewSet.urls()),
    ),
    path("from-formtools/squest/", include(squest.RequestAServiceViewSet.urls())),
    path("from-formtools/two-factor/", include(two_factor.SetupViewSet.urls())),
    path(
        "from-formtools/two-factor-single/",
        include(two_factor.SingleMethodSetupViewSet.urls()),
    ),
    path("linear-wizard/", include(views.LinearWizardViewSet.urls())),
    path("done-linear-wizard/", include(views.DoneLinearWizardViewSet.urls())),
    path("multi-value-wizard/", include(views.MultiValueWizardViewSet.urls())),
    path("other-linear-wizard/", include(views.OtherLinearWizardViewSet.urls())),
    path(
        "recreated-linear-wizard/", include(views.RecreatedLinearWizardViewSet.urls())
    ),
    path("branching-wizard/", include(views.BranchingWizardViewSet.urls())),
    path("switch-wizard/", include(views.SwitchWizardViewSet.urls())),
    path("switch-entry-wizard/", include(views.SwitchEntryWizardViewSet.urls())),
    path(
        "misdeclared-switch-wizard/",
        include(views.MisdeclaredSwitchWizardViewSet.urls()),
    ),
    path(
        "editing-branching-wizard/", include(views.EditingBranchingWizardViewSet.urls())
    ),
    path("done-branching-wizard/", include(views.DoneBranchingWizardViewSet.urls())),
    path("branch-entry-wizard/", include(views.BranchEntryWizardViewSet.urls())),
    path(
        "duplicate-context-wizard/", include(views.DuplicateContextWizardViewSet.urls())
    ),
    path("invalid-wizard/", include(views.InvalidWizardViewSet.urls())),
    path("form-view-step-wizard/", include(views.FormViewStepWizardViewSet.urls())),
    path(
        "missing-template-wizard/", include(views.MissingTemplateWizardViewSet.urls())
    ),
    path("empty-wizard/", include(views.EmptyWizardViewSet.urls())),
    path(
        "merged-payload-wizard/", include(views.MergedPayloadLinearWizardViewSet.urls())
    ),
    path(
        "path-aware-linear-wizard/", include(views.PathAwareLinearWizardViewSet.urls())
    ),
    path(
        "path-aware-form-view-first-step-wizard/",
        include(views.PathAwareFormViewFirstStepWizardViewSet.urls()),
    ),
    path(
        "branching-merged-payload-wizard/",
        include(views.BranchingMergedPayloadWizardViewSet.urls()),
    ),
    path(
        "empty-branch-arm-merged-payload-wizard/",
        include(views.EmptyBranchArmMergedPayloadWizardViewSet.urls()),
    ),
    path(
        "runtime-tree-branching-merge-wizard/",
        include(views.RuntimeTreeBranchingMergeViewSet.urls()),
    ),
    path("dynamic-wizard/", include(views.DynamicWizardViewSet.urls())),
    path(
        "dynamic-list-payload-wizard/",
        include(views.DynamicListPayloadWizardViewSet.urls()),
    ),
    path("file-uploading-wizard/", include(views.FileUploadingWizardViewSet.urls())),
    path("opening-hours-wizard/", include(views.OpeningHoursWizardViewSet.urls())),
    path("member-editing-wizard/", include(views.MemberEditingWizardViewSet.urls())),
    path("wizardless-wizard/", include(views.WizardlessWizardViewSet.urls())),
    path("file-editing-wizard/", include(views.FileEditingWizardViewSet.urls())),
    path("file-done-wizard/", include(views.FileDoneWizardViewSet.urls())),
    path(
        "one-time-token-done-wizard/",
        include(views.OneTimeTokenDoneWizardViewSet.urls()),
    ),
    path("sniffed-file-wizard/", include(views.SniffedFileWizardViewSet.urls())),
    path(
        "empty-branch-arm-context-finder-wizard/",
        include(views.EmptyBranchArmContextFinderViewSet.urls()),
    ),
    path(
        "branch-edit-rejection-wizard/",
        include(views.BranchEditRejectionWizardViewSet.urls()),
    ),
    path("routed-wizard/", include(views.RoutedWizardViewSet.urls())),
    path("unroutable-wizard/", include(views.UnroutableWizardViewSet.urls())),
    path("cross-branch-wizard/", include(views.CrossBranchWizardViewSet.urls())),
    path(
        "programmatic-lookup-wizard/",
        include(views.ProgrammaticLookupWizardViewSet.urls()),
    ),
    path(
        "misconfigured-wizard/",
        views.MisconfiguredStepUrlsWizardViewSet.as_view(),
        name="misconfigured-wizard",
    ),
    path(
        "misconfigured-wizard/<uuid:run_id>/",
        views.MisconfiguredStepUrlsWizardViewSet.as_view(),
        name="misconfigured-wizard-run",
    ),
    path(
        "org-scoped-wizard/<slug:org>/",
        include(views.OrgScopedEditingWizardViewSet.urls()),
    ),
    path(
        "walk-counting-wizard/",
        include(views.WalkCountingWizardViewSet.urls()),
    ),
    path("expand-wizard/", include(views.ExpandWizardViewSet.urls())),
    path(
        "empty-expand-wizard/",
        include(views.EmptyExpandWizardViewSet.urls()),
    ),
    path(
        "sealable-expand-wizard/",
        include(views.SealableExpandWizardViewSet.urls()),
    ),
    path(
        "branching-expand-wizard/",
        include(views.BranchingExpandWizardViewSet.urls()),
    ),
    path("stashing-wizard/", include(views.StashingWizardViewSet.urls())),
    path(
        "branching-stashing-wizard/",
        include(views.BranchingStashingWizardViewSet.urls()),
    ),
    path(
        "branching-stashing-wizard-resurrect/",
        views.resurrect_members_stash,
        name="branching-stashing-wizard-resurrect",
    ),
    path(
        "stashed-member-keys/",
        views.stashed_member_keys,
        name="stashed-member-keys",
    ),
    path(
        "discard-members-stash/",
        views.discard_members_stash,
        name="discard-members-stash",
    ),
    path(
        "resurrect-empty-stash/",
        views.resurrect_empty_stash,
        name="resurrect-empty-stash",
    ),
    path(
        "stashing-wizard-resurrect/",
        views.resurrect_contact_stash,
        name="stashing-wizard-resurrect",
    ),
    path(
        "required-photo-stashing-wizard/",
        include(views.RequiredPhotoStashingWizardViewSet.urls()),
    ),
    path(
        "required-photo-stashing-wizard-resurrect/",
        views.resurrect_required_photo_stash,
        name="required-photo-stashing-wizard-resurrect",
    ),
    path("summary-wizard/", include(views.SummaryWizardViewSet.urls())),
    path(
        "custom-summary-wizard/",
        include(views.CustomSummaryWizardViewSet.urls()),
    ),
    path(
        "summary-display-wizard/",
        include(views.SummaryDisplayWizardViewSet.urls()),
    ),
    path(
        "grouped-summary-wizard/",
        include(views.GroupedSummaryWizardViewSet.urls()),
    ),
    path(
        "templated-summary-wizard/",
        include(views.TemplatedSummaryWizardViewSet.urls()),
    ),
    path(
        "rendered-summary-wizard/",
        include(views.RenderedSummaryWizardViewSet.urls()),
    ),
    path(
        "colocated-summary-wizard/",
        include(views.ColocatedSummaryWizardViewSet.urls()),
    ),
    path(
        "declared-summary-wizard/",
        include(views.DeclaredSummaryWizardViewSet.urls()),
    ),
    path(
        "questioned-summary-wizard/",
        include(views.QuestionedSummaryWizardViewSet.urls()),
    ),
    path(
        "expanded-summary-wizard/",
        include(views.ExpandedSummaryWizardViewSet.urls()),
    ),
    path("escaped/", views.EscapeLandingView.as_view(), name="escape-landing"),
    path("escape-park-wizard/", include(views.EscapeParkWizardViewSet.urls())),
    path("escape-advance-wizard/", include(views.EscapeAdvanceWizardViewSet.urls())),
    path(
        "escape-advance-final-step-wizard/",
        include(views.EscapeAdvanceFinalStepWizardViewSet.urls()),
    ),
    path(
        "escape-obliterate-wizard/",
        include(views.EscapeObliterateWizardViewSet.urls()),
    ),
    path("bare-escape-wizard/", include(views.BareEscapeWizardViewSet.urls())),
    path("escape-editing-wizard/", include(views.EscapeEditingWizardViewSet.urls())),
    path(
        "mid-flow-escape-park-wizard/",
        include(views.MidFlowEscapeParkWizardViewSet.urls()),
    ),
    path(
        "escape-park-file-wizard/",
        include(views.EscapeParkFileWizardViewSet.urls()),
    ),
    path("scenario-task-list/", include(views.ScenarioViewSet.urls())),
    path("durable-task-list/", include(views.DurableViewSet.urls())),
    path("counting-task-list/", include(views.CountingViewSet.urls())),
    # A hub under an org prefix: the slug reaches every URL beneath it.
    path("org/<slug:org>/task-list/", include(views.OrgViewSet.urls())),
    path("gated-task-list/", include(views.GatedViewSet.urls())),
    # A hub under a journey segment, its members beneath it under the same.
    path("submit/<slug:journey>/", include(views.SubmitViewSet.urls())),
    path("party/", include(views.PartyViewSet.urls())),
    # Add-another pages mounted on their own, each returning to the party list.
    path("standalone-guests/", include(views.GuestsViewSet.urls())),
    path("locked-guests/", include(views.LockedGuestsViewSet.urls())),
    path("minimum-guests/", include(views.MinimumGuestsViewSet.urls())),
    path("advancing-guests/", include(views.AdvancingGuestsViewSet.urls())),
    path("anonymous-guests/", include(views.AnonymousGuestsViewSet.urls())),
    path("off-route-guests/", include(views.OffRouteGuestsViewSet.urls())),
    path("titled-guests/", include(views.TitledGuestsViewSet.urls())),
    path("durable-guests/", include(views.DurableGuestsViewSet.urls())),
    path("reshaped-guests/", include(views.ReshapedGuestsViewSet.urls())),
]
