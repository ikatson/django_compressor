import os.path
import re

from compressor.base import Compressor, SOURCE_HUNK, SOURCE_FILE
from compressor.conf import settings

from compressor.cache import get_hexdigest, get_mtime
from compressor.utils.decorators import cached_property


def get_lesscss_dependencies(filename, ignore=None):
    dirname = os.path.dirname(filename)
    imports = set()
    with open(filename) as f:
        for line in f.readlines():
            match = re.match('\s*@import\s+["\'](.*)[\'"];', line)
            if match:
                filename = match.group(1)
                assert not filename.startswith('/')
                filename = os.path.join(dirname, filename)
                imports.add(filename)
                if ignore and filename not in ignore:
                    imports |= get_lesscss_dependencies(filename, ignore=imports)
    return imports


class CssCompressor(Compressor):

    def __init__(self, content=None, output_prefix="css", context=None):
        super(CssCompressor, self).__init__(content=content,
            output_prefix=output_prefix, context=context)
        self.filters = list(settings.COMPRESS_CSS_FILTERS)
        self.type = output_prefix

    # Method added by Igor Katson
    @cached_property
    def mtimes(self):
        """Calculate mtimes taking all LESS dependencies into consideration."""
        result = []
        for kind, value, basename, elem in self.split_contents():
            if kind != SOURCE_FILE:
                continue
            result.append(str(get_mtime(value)))
            # If the file is LESS, extract mtimes of imports from it
            # recursively.
            if value.endswith('.less'):
               for value in sorted(get_lesscss_dependencies(value)):
                   result.append(str(get_mtime(value)))
        return result

    def split_contents(self):
        if self.split_content:
            return self.split_content
        self.media_nodes = []
        for elem in self.parser.css_elems():
            data = None
            elem_name = self.parser.elem_name(elem)
            elem_attribs = self.parser.elem_attribs(elem)
            if elem_name == 'link' and elem_attribs['rel'].lower() == 'stylesheet':
                basename = self.get_basename(elem_attribs['href'])
                filename = self.get_filename(basename)
                data = (SOURCE_FILE, filename, basename, elem)
            elif elem_name == 'style':
                data = (SOURCE_HUNK, self.parser.elem_content(elem), None, elem)
            if data:
                self.split_content.append(data)
                media = elem_attribs.get('media', None)
                # Append to the previous node if it had the same media type
                append_to_previous = self.media_nodes and self.media_nodes[-1][0] == media
                # and we are not just precompiling, otherwise create a new node.
                if append_to_previous and settings.COMPRESS_ENABLED:
                    self.media_nodes[-1][1].split_content.append(data)
                else:
                    node = CssCompressor(content=self.parser.elem_str(elem),
                                         context=self.context)
                    node.split_content.append(data)
                    self.media_nodes.append((media, node))
        return self.split_content

    def output(self, *args, **kwargs):
        if (settings.COMPRESS_ENABLED or settings.COMPRESS_PRECOMPILERS or
                kwargs.get('forced', False)):
            # Populate self.split_content
            self.split_contents()
            if hasattr(self, 'media_nodes'):
                ret = []
                for media, subnode in self.media_nodes:
                    subnode.extra_context.update({'media': media})
                    ret.append(subnode.output(*args, **kwargs))
                return ''.join(ret)
        return super(CssCompressor, self).output(*args, **kwargs)
