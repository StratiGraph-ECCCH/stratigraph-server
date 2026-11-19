# Sphinx configuration — stratigraph-server
#
# Mirrors stratigraph-templates' docs/conf.py (theme, MyST, version read from
# pyproject, LaTeX with XeLaTeX and DejaVu) with the names changed, and without
# what the server does not need. Two differences are deliberate:
#
# * the documents are NOT rewritten for Sphinx. They are the markdown files in
#   docs/ as they were, read by MyST; docs/index.md is the only page written
#   for the site, and it is a door, not a list;
# * no autodoc. The server's reference is its OpenAPI schema (`/docs` on any
#   node), which is generated from the code and held to it by
#   tests/test_la_documentazione_dice_il_vero.py; a second reference generated
#   here would be a second thing to keep aligned.
#
# The gate is `sphinx-build -W docs docs/_build`: a warning is an error.

import datetime
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# -- Project ----------------------------------------------------------------
project = 'StratiGraph Server'
copyright = f'2026-{datetime.datetime.now().year}, Emanuel Demetrescu — CNR-ISPC'
author = 'Emanuel Demetrescu'


def _read_version():
    """The server's version, never typed here: from pyproject.toml."""
    with open(os.path.join(ROOT, 'pyproject.toml'), encoding='utf-8') as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    if not m:
        raise RuntimeError('version not found in pyproject.toml')
    return m.group(1)


release = _read_version()
version = '.'.join(release.split('.')[:2])

# -- Extensions -------------------------------------------------------------
extensions = ['myst_parser']

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
master_doc = 'index'
source_suffix = {'.md': 'markdown'}
language = 'en'

# -- MyST -------------------------------------------------------------------
myst_enable_extensions = ['deflist', 'colon_fence', 'linkify']
myst_heading_anchors = 3

# The ARCHITECTURE page shows a placeholder (`{ … }`) inside a ```json block:
# Pygments highlights it in relaxed mode and says so. That is the only warning
# silenced here, and it is not about a broken page.
# EPUB non conosce il tipo di un .woff2 e, con -W, la sua lamentela
# («unknown mimetype … ignoring») ferma la pubblicazione: i caratteri del
# marchio servono alla pagina web, non al libro.
suppress_warnings = [
    'epub.unknown_project_files',  # i woff2 del marchio
    'misc.highlighting_failure',
]

# -- HTML -------------------------------------------------------------------
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# Il marchio, vendorizzato da `stratigraph-brand` con il suo
# `docs-theme/sync-brand-docs.sh`, come lo vendorizzano le applicazioni: un
# manuale letto in trincea non ha una CDN. Chiaro e scuro seguono
# l'impostazione di sistema di chi legge; i contrasti sono misurati nel
# marchio. Per cambiare un colore si cambia lì, e si ridà il sync.
html_css_files = [
    'brand/stratigraph-theme.css',
    'brand/sphinx-rtd-bridge.css',
]
# L'interruttore delle due facce: chiaro, scuro, come il sistema. Senza
# scelta esplicita vale il sistema di chi legge, che è il modo di serie.
html_js_files = ['brand/brand-theme-toggle.js']

html_theme_options = {
    'prev_next_buttons_location': 'bottom',
    'collapse_navigation': True,
    'sticky_navigation': True,
    'navigation_depth': 3,
    'titles_only': False,
}
html_context = {
    'display_github': True,
    'github_user': 'StratiGraph-ECCCH',
    'github_repo': 'stratigraph-server',
    'github_version': 'main',
    'conf_py_path': '/docs/',
}
html_last_updated_fmt = '%d %b %Y'

# -- LaTeX / PDF (as in s3Dgraphy and stratigraph-templates) ----------------
latex_engine = 'xelatex'
latex_use_xindy = False
latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '10pt',
    'figure_align': 'htbp',
    'fontpkg': r"""
\IfFontExistsTF{DejaVu Serif}
  {\setmainfont{DejaVu Serif}}
  {\IfFontExistsTF{FreeSerif}{\setmainfont{FreeSerif}}{}}
\IfFontExistsTF{DejaVu Sans}
  {\setsansfont{DejaVu Sans}}
  {\IfFontExistsTF{FreeSans}{\setsansfont{FreeSans}}{}}
\IfFontExistsTF{DejaVu Sans Mono}
  {\setmonofont{DejaVu Sans Mono}[Scale=MatchLowercase]}
  {\IfFontExistsTF{FreeMono}{\setmonofont{FreeMono}[Scale=MatchLowercase]}{}}
""",
    'preamble': r"""
\sloppy
""",
}
latex_documents = [
    ('index', 'stratigraph-server.tex', 'StratiGraph Server',
     'Emanuel Demetrescu', 'manual'),
]
latex_show_urls = 'footnote'

# -- Links that leave docs/ -------------------------------------------------
# The documents were written to be read in the repository, so they link to
# files of this repository beside them as files: `../dev-stack/README-DEV.md`.
# On the site those are not pages. Rather than rewriting the documents, this
# pass reads each such link against the FILE that contains it and sends it to
# its blob on GitHub. A link this pass does not understand is left to MyST,
# which warns, and `-W` makes the warning an error.
#
# Another repository is NOT resolved here (19 November 2026): a document of a
# sibling repository is written with its whole address, because a relative
# `../../s3Dgraphy` works only on a disk where the repositories are sibling
# folders, and on GitHub it is a 404. `tests/test_docs_link_veri.py` keeps every
# relative link inside the repository; one that slipped past it would reach
# MyST here, and `-W` would stop the build.
_THIS = 'https://github.com/StratiGraph-ECCCH/stratigraph-server'

from sphinx.transforms.post_transforms import SphinxPostTransform  # noqa: E402


def _outside_uri(raw, source_file):
    """The GitHub address of a link that leaves docs/, or None."""
    if not raw or '://' in raw or raw.startswith('#'):
        return None
    path, _, anchor = raw.partition('#')
    here = os.path.dirname(source_file)
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(here, path))
    if full == ROOT or full.startswith(ROOT + os.sep):
        rel = os.path.relpath(full, ROOT).replace(os.sep, '/')
        if rel == 'docs' or rel.startswith('docs/'):
            return None                       # a page of the site: MyST's
        for cand in (full, full + '.md'):
            if os.path.isfile(cand):
                rel = os.path.relpath(cand, ROOT).replace(os.sep, '/')
                return f'{_THIS}/blob/HEAD/{rel}' + (f'#{anchor}' if anchor else '')
        if os.path.isdir(full):
            return _THIS if rel == '.' else f'{_THIS}/tree/HEAD/{rel}'
        return None
    return None


class OutsideLinks(SphinxPostTransform):
    default_priority = 8          # before MystReferenceResolver (9)

    def run(self, **kwargs):
        from docutils import nodes
        from sphinx import addnodes
        for node in list(self.document.findall(addnodes.pending_xref)):
            if node.get('reftype') != 'myst':
                continue
            source = node.source or self.env.doc2path(self.env.docname)
            uri = _outside_uri(node.get('reftarget') or '', str(source))
            if uri is None:
                continue
            ref = nodes.reference('', '', internal=False, refuri=uri)
            ref += node.children
            node.replace_self(ref)


def setup(app):
    app.add_post_transform(OutsideLinks)
