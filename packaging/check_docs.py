"""Check local Markdown/image links without requiring a public repository."""
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def outside_code(content: str) -> str:
    return re.sub(r'^```[^\n]*\n.*?^```[^\n]*$', '', content, flags=re.M | re.S)


def anchors(content: str) -> set[str]:
    content = outside_code(content)
    found = set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', content))
    used: dict[str, int] = {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', content, flags=re.M):
        title = re.sub(r'<[^>]*>', '', title)
        title = re.sub(r'\[([^]]*)\]\([^)]*\)', r'\1', title)
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = used.get(slug, 0)
        used[slug] = count + 1
        found.add(slug if count == 0 else f'{slug}-{count}')
    return found


def main() -> int:
    errors = []
    anchor_cache: dict[Path, set[str]] = {}
    for path in [ROOT / 'README.md', ROOT / 'README.ja.md', ROOT / 'THIRD_PARTY_NOTICES.md', ROOT / 'images/README.md', *sorted((ROOT / 'docs').rglob('*.md')), *sorted((ROOT / '.github').glob('*.md'))]:
        content = outside_code(path.read_text())
        links = re.findall(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)', content)
        links += re.findall(r'(?:src|srcset|href)="([^"]+)"', content)
        for link in links:
            if link.startswith(('http:', 'https:', 'mailto:')):
                continue
            parts = urlsplit(link)
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            if not target.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing link {link}')
            elif target.suffix == '.md' and parts.fragment:
                if target not in anchor_cache:
                    anchor_cache[target] = anchors(target.read_text())
                if unquote(parts.fragment) not in anchor_cache[target]:
                    errors.append(f'{path.relative_to(ROOT)}: missing section {link}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Local documentation links, section anchors and image references are valid.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
