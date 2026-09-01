# Chapter 8 — Escapes: leaving the wizard

Sometimes an answer means the user should not be in the wizard any more.
An email address that already has an account should send the applicant to
log in, not to the next step. That is not a branch — there is no arm to
take — and it is not a validation error, because the address is perfectly
valid. It is a way out.

A step says so by raising an **escape**, an ordinary exception in the
spirit of `Http404`. It can be raised from the form's `clean()`, or from a
step view's `form_valid()` when the decision needs the request:

```python
from gandalf.escapes import Park


class EmailLookupForm(forms.Form):
    email = forms.EmailField(label="Email address")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park(reverse("readme-login"))
        return cleaned_data


def with_contact_and_review(wizard):
    return (
        wizard.step(EmailLookupForm, name="contact", label="Email")
        .step(WebsiteStepView, name="website", label="Website")
        .step(AddressForm, name="address", label="Address")
        .step(ReviewStepView, name="review")
    )
```

The wizard's remaining chapters build on this tail: a contact step that may
escape, chapter 6's website step, the address and chapter 7's summary.

All three escapes take the same arguments as `django.shortcuts.redirect`.
Which one you raise decides what happens to the escaping answer, and so
what the user comes back to if they return to the run:

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded | the same step, unanswered |
| `Advance` | stored | the next step |
| `Obliterate` | destroyed with the run | a fresh run |

`Park` is the detour: the login page was a side trip, and the email step is
waiting when they get back. `Advance` is for an answer that stands but has
consequences elsewhere first — read the terms, then carry on. `Obliterate`
is for an answer that ends the application: a country the fund does not
cover.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/escape/ (answer
> `existing@example.com` to be parked) &nbsp;·&nbsp; **Source:** [`ch08_escapes.py`](../../tests/testapp/readme/ch08_escapes.py) &nbsp;·&nbsp; **Reference:** [Escapes](../reference/escapes.md)

---

[← Chapter 7 — The summary: check your answers](07-the-summary.md) · [Learn](README.md) · [Chapter 9 — File uploads →](09-file-uploads.md)
