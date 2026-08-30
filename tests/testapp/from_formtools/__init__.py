"""Real `django-formtools` wizards, translated.

[Coming from django-formtools](../../../docs/learn/coming-from-django-formtools.md)
maps the pieces — a `form_list` becomes chained `.step()` calls, a
`condition_dict` becomes `.branch()` — with snippets written to make the
mapping legible. Snippets prove a mapping; they do not prove it survives
contact. These are three wizards taken from projects that ship, translated
whole and driven end to end by `tests/functional/test_from_formtools.py`, so
a claim the docs make about porting is a claim something runs.

Three rather than one because they fail differently, and the interesting
part of a port is which half of the library it lands in:

| Module | Upstream | What the port turns on |
| --- | --- | --- |
| `djangogirls` | [DjangoGirls/djangogirls](https://github.com/DjangoGirls/djangogirls) `organize/views.py` (BSD-3-Clause) | the declaration — a three-entry `condition_dict` becomes two `.branch()` nodes |
| `squest` | [HewlettPackard/squest](https://github.com/HewlettPackard/squest) `service_catalog/views/catalog_views.py` (Apache-2.0) | a step view — a later form built from an earlier answer |
| `two_factor` | [jazzband/django-two-factor-auth](https://github.com/jazzband/django-two-factor-auth) `two_factor/views/core.py` (MIT) | the run — a shape decided per request, and a check that consumes what it checks |

None of this is upstream's code. Each module is a Gandalf declaration of the
same *flow*, with the forms trimmed to the fields the shape depends on and
the domain models replaced by whatever the smallest honest stand-in is — the
projects are named so the comparison can be checked, not because anything
was copied from them.

The point of each is in its module docstring, under **What upstream has to
do by hand**. That is the part worth reading: not that the port is possible,
but what stops being your problem once it is done.
"""
