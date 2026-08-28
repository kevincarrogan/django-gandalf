from django.urls import include, path

from . import views
from .readme import (
    ch01_first_wizard,
    ch02_branching,
    ch03_switch,
    ch04_expand,
    ch05_funds,
    ch06_review,
    ch07_step_views,
    ch08_uploads,
    ch09_records,
    ch10_stash,
    ch11_hub,
    ch12_budget,
    ch13_gated,
    ch14_journey,
)


urlpatterns = [
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
    path(
        "readme/funds/<slug:fund>/", include(ch05_funds.FundApplicationViewSet.urls())
    ),
    path("readme/review/", include(ch06_review.ReviewedApplicationViewSet.urls())),
    path(
        "readme/step-view/", include(ch07_step_views.LookedUpApplicationViewSet.urls())
    ),
    path("readme/login/", ch07_step_views.login_placeholder, name="readme-login"),
    path("readme/upload/", include(ch08_uploads.DocumentedApplicationViewSet.urls())),
    path("readme/record/", include(ch09_records.RecordedApplicationViewSet.urls())),
    path(
        "readme/received/<int:pk>/",
        ch09_records.application_received,
        name="readme-received",
    ),
    path("readme/stash/", include(ch10_stash.ContactDetailsViewSet.urls())),
    path(
        "readme/stash-reopen/",
        ch10_stash.reopen_contact_details,
        name="readme-stash-reopen",
    ),
    # A hub and its sections are siblings: the hub's "<slug:section>/" door
    # would swallow anything mounted beneath it.
    path("readme/hub/", include(ch11_hub.GrantHubView.urls())),
    path("readme/hub-contact/", include(ch11_hub.ContactSectionViewSet.urls())),
    path("readme/hub-address/", include(ch11_hub.AddressSectionViewSet.urls())),
    # A collection page and its item wizard are siblings of each other and of
    # the hub, for the same reason.
    path("readme/project/", include(ch12_budget.ProjectHubView.urls())),
    path("readme/project-details/", include(ch12_budget.ProjectSectionViewSet.urls())),
    path("readme/budget/", include(ch12_budget.BudgetCollectionView.urls())),
    path(
        "readme/budget-line/<uuid:item>/", include(ch12_budget.BudgetLineViewSet.urls())
    ),
    path("readme/gated/", include(ch13_gated.GatedHubView.urls())),
    path(
        "readme/gated-project/", include(ch13_gated.GatedProjectSectionViewSet.urls())
    ),
    path("readme/gated-referees/", include(ch13_gated.RefereesSectionViewSet.urls())),
    path(
        "readme/gated-match-funding/",
        include(ch13_gated.MatchFundingSectionViewSet.urls()),
    ),
    # A journey: the setup wizard mints an id, and the hub, its sections, the
    # budget page and the budget line wizard are all mounted under it as
    # siblings. "new" is listed before the journey pattern so it is never
    # read as an id.
    path("readme/apply/new/", include(ch14_journey.ApplicationStartViewSet.urls())),
    path(
        "readme/apply/<slug:journey>/",
        include(ch14_journey.GrantApplicationHubView.urls()),
    ),
    path(
        "readme/apply-setup/<slug:journey>/",
        include(ch14_journey.SetupSectionViewSet.urls()),
    ),
    path(
        "readme/apply-contact/<slug:journey>/",
        include(ch14_journey.ContactSectionViewSet.urls()),
    ),
    path(
        "readme/apply-project/<slug:journey>/",
        include(ch14_journey.ProjectSectionViewSet.urls()),
    ),
    path(
        "readme/apply-budget/<slug:journey>/",
        include(ch14_journey.BudgetCollectionView.urls()),
    ),
    path(
        "readme/apply-budget-line/<slug:journey>/<uuid:item>/",
        include(ch14_journey.BudgetLineViewSet.urls()),
    ),
    path(
        "readme/apply-match-funding/<slug:journey>/",
        include(ch14_journey.MatchFundingSectionViewSet.urls()),
    ),
    path(
        "readme/apply-referees/<slug:journey>/",
        include(ch14_journey.RefereesSectionViewSet.urls()),
    ),
    path(
        "readme/apply-documents/<slug:journey>/",
        include(ch14_journey.DocumentsSectionViewSet.urls()),
    ),
    # A hub that is a section of the hub above: a sibling too, under the
    # same journey segment.
    path(
        "readme/apply-supporting/<slug:journey>/",
        include(ch14_journey.SupportingHubView.urls()),
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
    path(
        "wizard-configured-storage/",
        include(views.WizardConfiguredStorageViewSet.urls()),
    ),
    path("form-view-step-wizard/", include(views.FormViewStepWizardViewSet.urls())),
    path(
        "missing-template-wizard/", include(views.MissingTemplateWizardViewSet.urls())
    ),
    path("pre-configured-wizard/", include(views.PreConfiguredWizardViewSet.urls())),
    path("empty-wizard/", include(views.EmptyWizardViewSet.urls())),
    path(
        "double-configured-wizard/", include(views.DoubleConfiguredWizardViewSet.urls())
    ),
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
    path("section-editing-wizard/", include(views.SectionEditingWizardViewSet.urls())),
    path("wizardless-wizard/", include(views.WizardlessWizardViewSet.urls())),
    path("file-editing-wizard/", include(views.FileEditingWizardViewSet.urls())),
    path("file-done-wizard/", include(views.FileDoneWizardViewSet.urls())),
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
        views.resurrect_sections_stash,
        name="branching-stashing-wizard-resurrect",
    ),
    path(
        "stashed-section-keys/",
        views.stashed_section_keys,
        name="stashed-section-keys",
    ),
    path(
        "discard-sections-stash/",
        views.discard_sections_stash,
        name="discard-sections-stash",
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
    path("scenario-hub/", include(views.ScenarioHubView.urls())),
    path("scenario-hub-plain/", include(views.PlainSectionViewSet.urls())),
    path("scenario-hub-advancing/", include(views.AdvancingSectionViewSet.urls())),
    path("durable-hub/", include(views.DurableHubView.urls())),
    path("durable-section/", include(views.DurableSectionViewSet.urls())),
    path("counting-hub/", include(views.CountingHubView.urls())),
    path(
        "counting-hub-section/",
        include(views.CountingSectionViewSet.urls()),
    ),
    path(
        "other-counting-hub-section/",
        include(views.OtherCountingSectionViewSet.urls()),
    ),
    path("org/<slug:org>/hub/", include(views.OrgHubView.urls())),
    path("org/<slug:org>/hub-details/", include(views.OrgSectionViewSet.urls())),
    # A hub, a collection page and an item wizard are all mounted as
    # *siblings*, never nested, and for two distinct reasons.
    #
    # `HubView.urls()` publishes "<slug:section>/", which matches any single
    # segment — so a collection page mounted at "party/guests/" would be
    # swallowed by the hub's own door for a section named "guests".
    #
    # `WizardViewSet.urls()` publishes "" as its start URL — so an item wizard
    # mounted at "party-guests/<uuid:item>/" would occupy the exact path of
    # the collection's own door for that item. Either way, whichever
    # `include()` comes first silently wins.
    path("gated-hub/", include(views.GatedHubView.urls())),
    # A hub under a journey segment, its sections beside it under the same.
    path("submit/<slug:journey>/", include(views.SubmitHubView.urls())),
    path(
        "submit-first/<slug:journey>/", include(views.SubmitFirstSectionViewSet.urls())
    ),
    path(
        "submit-second/<slug:journey>/",
        include(views.SubmitSecondSectionViewSet.urls()),
    ),
    path("gated-first/", include(views.GatedFirstSectionViewSet.urls())),
    path("gated-second/", include(views.GatedSecondSectionViewSet.urls())),
    path("party/", include(views.PartyHubView.urls())),
    path("party-venue/", include(views.PartyVenueSectionViewSet.urls())),
    path("party-guests/", include(views.GuestCollectionView.urls())),
    path("party-guest/<uuid:item>/", include(views.GuestItemViewSet.urls())),
    path("locked-guests/", include(views.LockedGuestCollectionView.urls())),
    path("locked-guest/<uuid:item>/", include(views.LockedGuestItemViewSet.urls())),
    path("minimum-guests/", include(views.MinimumGuestCollectionView.urls())),
    path("minimum-guest/<uuid:item>/", include(views.MinimumGuestItemViewSet.urls())),
    path("drifted-guests/", include(views.DriftedGuestCollectionView.urls())),
    path("drifted-guest/<uuid:item>/", include(views.DriftedGuestItemViewSet.urls())),
    path("advancing-guests/", include(views.AdvancingGuestCollectionView.urls())),
    path(
        "advancing-guest/<uuid:item>/",
        include(views.AdvancingGuestItemViewSet.urls()),
    ),
    path("org/<slug:org>/guests/", include(views.OrgGuestCollectionView.urls())),
    path(
        "org/<slug:org>/guest/<uuid:item>/",
        include(views.OrgGuestItemViewSet.urls()),
    ),
    path("anonymous-guests/", include(views.AnonymousGuestCollectionView.urls())),
    path(
        "anonymous-guest/<uuid:item>/",
        include(views.AnonymousGuestItemViewSet.urls()),
    ),
    path("off-route-guests/", include(views.OffRouteGuestCollectionView.urls())),
    path(
        "off-route-guest/<uuid:item>/",
        include(views.OffRouteGuestItemViewSet.urls()),
    ),
    path("durable-guests/", include(views.DurableGuestCollectionView.urls())),
    path(
        "durable-guest/<uuid:item>/",
        include(views.DurableGuestItemViewSet.urls()),
    ),
    path("reshaped-guests/", include(views.ReshapedGuestCollectionView.urls())),
    path(
        "reshaped-guest/<uuid:item>/",
        include(views.ReshapedGuestItemViewSet.urls()),
    ),
]
