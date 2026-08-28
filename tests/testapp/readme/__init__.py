"""The README's worked example: one grant application, built up chapter by
chapter.

Each module here is one chapter of ``README.md`` — the exact code the chapter
shows, mounted under ``readme/`` so that ``just serve`` exposes it and
``tests/functional/test_readme_examples.py`` drives it. A chapter imports the
one before it and grows it, which is the first thing the README teaches: a
``Wizard`` is a value, so the previous chapter's declaration is still intact
after this one has built on it.

The forms live in ``forms.py`` and are shared, because a grant application
asks the same questions whichever chapter it has reached.
"""
