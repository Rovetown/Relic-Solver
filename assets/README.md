# Design-time assets

Nothing in this directory is served by the web app or shipped to production. It
holds source artwork that exists so new sprites can be drawn or sliced from it.

`assets/` is listed in both `.dockerignore` and `.slugignore`, so the directory is
present in the repository and in every clone, but absent from the container image
and from the Heroku slug.

## `sprite-sources/`

| File | What it is |
|------|------------|
| `Blank_Button.webp` | empty button sprite, a base for new button artwork |
| `Item_Chest.webp` | chest sprite, kept for a future relic row |
| `pixilart-selection-green.png` | green 9-slice border; the deployed build uses `pixil-frame-0.webp` instead |

To put one of these on the site, copy (do not move) the file into
`src/webapp/static/images/`, convert it to WebP if it is still a PNG, and
reference it from a template or stylesheet.
