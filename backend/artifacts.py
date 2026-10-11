"""Artifact validation and safe Markdown rendering."""
import bleach
from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "strong", "ul",
}
ALLOWED_ATTRIBUTES = {"a": ["href", "title"], "code": ["class"]}


def render_markdown(source: str) -> str:
    """Render CommonMark and allowlist output tags, attributes, and URL schemes."""
    html = MARKDOWN.render(source)
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
