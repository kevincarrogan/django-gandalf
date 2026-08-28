# Appendix B — Configuration

Declaring steps is usually all you need; `.configure(...)` overrides a runtime
default when you want one. It is optional — a `WizardViewSet` configures a
plain `Wizard` with defaults automatically.

```python
wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .configure(file_storage_class=TenantFileStorage, observer_class=CountRejections)
)
```

The same keyword pattern applies to every touch point on the configured
wizard — `template_name`, `form_view_factory`, `cursor_walker_class`,
`step_dispatcher_class`, `state_serializer_class`, `step_router_class`,
`file_storage_class` and `observer_class`. Each has a sensible default, so
you only configure what you need. A pre-configured wizard is taken as-is by
the viewset, so set `template_name` there too, as chapter 14's setup wizard
does. `storage_class` is the one thing set on the viewset instead, for the
reason chapter 9 gives.

For a runtime-level view of how the pieces fit together, see
[ARCHITECTURE.md](../ARCHITECTURE.md). For driving a wizard programmatically —
an AI agent submitting steps as data instead of clicking the forms — see
[AGENT_ACCESS.md](../AGENT_ACCESS.md).

---

[← Appendix A — Testing your wizards](appendix-a-testing-your-wizards.md) · [README](../README.md) · [Appendix C — What replaying costs →](appendix-c-what-replaying-costs.md)
