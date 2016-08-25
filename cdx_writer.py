#!/usr/bin/env python

""" Copyright(c)2012-2016 Internet Archive. Software license AGPL version 3.

This script requires a modified version of Hanzo Archives' warc-tools:
http://code.hanzoarchives.com/warc-tools/src/tip/hanzo/warctools

This script is loosely based on warcindex.py:
http://code.hanzoarchives.com/warc-tools/src/1897e2bc9d29/warcindex.py

The functions that start with "get_" (as opposed to "parse_") are called by the
dispatch loop in make_cdx using getattr().

Jan 2016: Modified to include language
May 2016: Modified to include simhash
"""

try:
    from warctools import ArchiveRecord #from https://bitbucket.org/rajbot/warc-tools
except ImportError:
    from hanzo.warctools import ArchiveRecord #from https://bitbucket.org/rajbot/warc-tools
from surt      import surt          #from https://github.com/rajbot/surt
from surt      import DefaultIAURLCanonicalizer

import os
import re
import sys
import base64
import chardet
import hashlib
import json
import urllib
import urlparse
import string
import resource
from itertools import groupby
from datetime  import datetime
from optparse  import OptionParser

content_features_disabled = False
try:
    import lxml.html
    from lxml.html.clean import Cleaner
    import cld2full as cld2
    from simhash import Simhash
except ImportError:
    content_features_disabled = True

class ParseError(Exception):
    pass

class CDX_Writer(object):
    # init()
    #___________________________________________________________________________
    def __init__(self, file, out_file=sys.stdout, format="N b a m s k r M S V g", use_full_path=False, file_prefix=None, all_records=False, screenshot_mode=False, exclude_list=None, stats_file=None, canonicalizer_options=None, content_features=False):

        self.field_map = {'M': 'AIF meta tags',
                          'N': 'massaged url',
                          'S': 'compressed record size',
                          'V': 'compressed arc file offset',
                          'a': 'original url',
                          'b': 'date',
                          'g': 'file name',
                          'k': 'new style checksum',
                          'm': 'mime type',
                          'r': 'redirect',
                          's': 'response code',
                          'Q': 'language string',
                          'C': 'simhash'
                         }

        self.file                  = file
        self.out_file              = out_file
        self.content_features      = content_features
        self.format                = format
        self.all_records           = all_records
        self.screenshot_mode       = screenshot_mode
        self.canonicalizer_options = canonicalizer_options or {}
        self.crlf_pattern          = re.compile('\r?\n\r?\n')
        self.response_pattern      = re.compile('^application/http;\s*msgtype=response$', re.I)

        #similar to what what the wayback uses:
        self.fake_build_version = "archive-commons.0.0.1-SNAPSHOT-20120112102659-python"

        #these fields are set for each record in the warc
        self.offset        = 0
        self.surt          = None
        self.mime_type     = None
        self.headers       = None
        self.content       = None
        self.meta_tags     = None
        self.response_code = None

        #content based features
        self.extracted_text  = None
        self.language_string = None
        self.simhash         = None

        #Large html files cause lxml to segfault
        #problematic file was 154MB, we'll stop at 5MB
        self.lxml_parse_limit = 5 * 1024 * 1024

        if use_full_path:
            self.warc_path = os.path.abspath(file)
        elif file_prefix:
            self.warc_path = os.path.join(file_prefix, file)
        else:
            self.warc_path = file

        if exclude_list:
            if not os.path.exists(exclude_list):
                raise IOError, "Exclude file not found"
            self.excludes = []
            f = open(exclude_list, 'r')
            for line in f:
                if '' == line.strip():
                    continue
                url = line.split()[0]
                self.excludes.append(self.urlkey(url))
        else:
            self.excludes = None

        if stats_file:
            if os.path.exists(stats_file):
                raise IOError, "Stats file already exists"
            self.stats_file = stats_file
        else:
            self.stats_file = None

    def canonicalize(self, hurl):
        return DefaultIAURLCanonicalizer.canonicalize(
            hurl, **dict(self.canonicalizer_options))

    def urlkey(self, url):
        """compute urlkey from `url`."""
        return surt(url, canonicalizer=self.canonicalize)

    # parse_http_header()
    #___________________________________________________________________________
    def parse_http_header(self, header_name):
        if self.headers is None:
            return None

        pattern = re.compile(header_name+':\s*(.+)', re.I)
        for line in iter(self.headers):
            m = pattern.match(line)
            if m:
                return m.group(1)
        return None

    # parse_http_content_type_header()
    #___________________________________________________________________________
    def parse_http_content_type_header(self, record):
        content_type = self.parse_http_header('content-type')
        if content_type is None:
            return 'unk'

        # some http responses end abruptly: ...Content-Length: 0\r\nConnection: close\r\nContent-Type: \r\n\r\n\r\n\r\n'
        content_type = content_type.strip()
        if '' == content_type:
            return 'unk'

        m = re.match('(.+?);', content_type)
        if m:
            content_type = m.group(1)

        if re.match('^[a-z0-9\-\.\+/]+$', content_type):
            return content_type
        else:
            return 'unk'


    # parse_charset()
    #___________________________________________________________________________
    def parse_charset(self):
        charset = None
        charset_pattern = re.compile('charset\s*=\s*([a-z0-9_\-]+)', re.I)

        content_type = self.parse_http_header('content-type')
        if content_type:
            m = charset_pattern.search(content_type)
            if m:
                charset = m.group(1)


        if charset is None and self.meta_tags is not None:
            content_type = self.meta_tags.get('content-type')
            if content_type:
                m = charset_pattern.search(content_type)
                if m:
                    charset = m.group(1)

        if charset:
            charset = charset.replace('win-', 'windows-')

        return charset

    # parse_meta_tags
    #___________________________________________________________________________
    def parse_meta_tags(self, record):
        """We want to parse meta tags in <head>, even if not direct children.
        e.g. <head><noscript><meta .../></noscript></head>

        What should we do about multiple meta tags with the same name?
        currently, we append the content attribs together with a comma seperator.

        We use either the 'name' or 'http-equiv' attrib as the meta_tag dict key.
        """

        if not ('response' == record.type and 'text/html' == self.mime_type):
            return None

        if self.content is None:
            return None

        meta_tags = {}

        #lxml.html can't parse blank documents
        html_str = self.content.strip()
        if '' == html_str:
            return meta_tags

        #lxml can't handle large documents
        if record.content_length > self.lxml_parse_limit:
            return meta_tags

        # lxml was working great with ubuntu 10.04 / python 2.6
        # On ubuntu 11.10 / python 2.7, lxml exhausts memory hits the ulimit
        # on the same warc files. Unfortunately, we don't ship a virtualenv,
        # so we're going to give up on lxml and use regexes to parse html :(

        meta_tags = {}
        for x in re.finditer("(<meta[^>]+?>|</head>)", html_str, re.I):
            #we only want to look for meta tags that occur before the </head> tag
            if x.group(1).lower() == '</head>':
                break
            name = None
            content = None

            m = re.search(r'''\b(?:name|http-equiv)\s*=\s*(['"]?)(.*?)(\1)[\s/>]''', x.group(1), re.I)
            if m:
                name = m.group(2).lower()
            else:
                continue

            m = re.search(r'''\bcontent\s*=\s*(['"]?)(.*?)(\1)[\s/>]''', x.group(1), re.I)
            if m:
                content = m.group(2)
            else:
                continue

            if name not in meta_tags:
                meta_tags[name] = content
            else:
                if 'refresh' != name:
                    #for redirect urls, we only want the first refresh tag
                    meta_tags[name] += ',' + content

        return meta_tags


    # get_AIF_meta_tags() //field "M"
    #___________________________________________________________________________
    def get_AIF_meta_tags(self, record):
        """robot metatags, if present, should be in this order: A, F, I
        """
        x_robots_tag = self.parse_http_header('x-robots-tag')

        robot_tags = []
        if self.meta_tags and 'robots' in self.meta_tags:
            robot_tags += self.meta_tags['robots'].split(',')
        if x_robots_tag:
            robot_tags += x_robots_tag.split(',')
        robot_tags = [x.strip().lower() for x in robot_tags]

        s = ''


        if 'noarchive' in robot_tags:
            s += 'A'
        if 'nofollow' in robot_tags:
            s += 'F'
        if 'noindex' in robot_tags:
            s += 'I'

        # IA-proprietary extension 'R' flag for warc/revisit records.
        if 'revisit' == record.type:
            s += 'R'

        # IA-proprietary extension 'P' flag for password protected pages.
        # crawler adds special header to WARC record, whose value consists
        # of three values separated by comma. The first value is a number
        # of attempted logins (so >0 value means captured with login).
        # Example: ``1,1,http://(com,example,)/``
        sfps = record.get_header('WARC-Simple-Form-Province-Status')
        if sfps:
            sfps = sfps.split(',', 2)
            try:
                if int(sfps[0]) > 0:
                    s += 'P'
            except ValueError as ex:
                pass

        if s:
            return ''.join(s)
        else:
            return '-'


    # get_massaged_url() //field "N"
    #___________________________________________________________________________
    def get_massaged_url(self, record, use_precalculated_value=True):
        if use_precalculated_value:
            return self.surt

        if 'warcinfo' == record.type:
            return self.get_original_url(record)
        else:
            url = record.url
            if self.screenshot_mode:
                url = 'http://web.archive.org/screenshot/'+url

            try:
                return self.urlkey(url)
            except:
                return self.get_original_url(record)


    # get_compressed_record_size() //field "S"
    #___________________________________________________________________________
    def get_compressed_record_size(self, record):
        size = record.compressed_record_size
        if size is None:
            size = "-"

        return str(size)


    # get_compressed_arc_file_offset() //field "V"
    #___________________________________________________________________________
    def get_compressed_arc_file_offset(self, record):
        return str(self.offset)


    # get_original_url() //field "a"
    #___________________________________________________________________________
    def get_original_url(self, record):
        if 'warcinfo' == record.type:
            url = 'warcinfo:/%s/%s' % (self.file, self.fake_build_version)
            return url

        url = record.url

        # There are few arc files from 2002 that have non-ascii characters in
        # the url field. These are not utf-8 characters, and the charset of the
        # page might not be specified, so use chardet to try and make these usable.
        if isinstance(url, str):
            try:
                url.decode('ascii')
            except UnicodeDecodeError:
                enc = chardet.detect(url)
                if enc and enc['encoding']:
                    if 'EUC-TW' == enc['encoding']:
                        # We don't have the EUC-TW encoding installed, and most likely
                        # something is so wrong that we probably can't recover this url
                        url = url.decode('Big5', 'replace')
                    else:
                        url = url.decode(enc['encoding'], 'replace')
                else:
                    url = url.decode('utf-8', 'replace')

        # Some arc headers contain urls with the '\r' character, which will cause
        # problems downstream when trying to process this url, so escape it.
        # While we are at it, replace other newline chars.
        url = url.replace('\r', '%0D')
        url = url.replace('\n', '%0A')
        url = url.replace('\x0c', '%0C') #formfeed
        url = url.replace('\x00', '%00') #null may cause problems with downstream C programs

        if self.screenshot_mode:
            url = u'http://web.archive.org/screenshot/' + url

        return url

    # get_date() //field "b"
    #___________________________________________________________________________
    def get_date(self, record):
        #warcs and arcs use a different date format
        #consider using dateutil.parser instead

        if record.date.isdigit():
            date_len = len(record.date)
            if 14 == date_len:
                #arc record already has date in the format we need
                return record.date
            elif 16 == date_len:
                #some arc records have 16-digit dates: 2000082305410049
                return record.date[:14]
            elif 18 == date_len:
                #some arc records have 18-digit dates: 200009180023002953
                return record.date[:14]
            elif 12 == date_len:
                #some arc records have 12-digit dates: 200011201434
                return record.date + '00'
        elif re.match('^[a-f0-9]+$', record.date):
            #some arc records have a hex string in the date field
            return '-'

        #warc record
        date = datetime.strptime(record.date, "%Y-%m-%dT%H:%M:%SZ")
        return date.strftime("%Y%m%d%H%M%S")

    # extract_text()
    #___________________________________________________________________________
    def extract_text(self, record):

        result = None
        if not ('response' == record.type and self.response_code == '200'):
            return None
        if self.mime_type != 'text/html':
            return None
        if self.content is None or record.content_length > self.lxml_parse_limit:
            return None
        html_string = self.content
        cleaner = Cleaner()
        cleaner.javascript = True
        cleaner.style = True
        try:
            root = lxml.html.fromstring(html_string)
            root = cleaner.clean_html(root)
            text_content = root.text_content().encode('utf-8')
            result = text_content
        except:
            pass
        return result

    # get_language_string() //field "Q"
    #___________________________________________________________________________
    def get_language_string(self, record):

        result = '-'
        text_string = self.extracted_text
        if text_string is None:
            return result
        isReliable = None
        details = None
        try:
            isReliable, textBytesFound, details = cld2.detect(text_string)
            lang_codes_with_pct = []
            if isReliable:
                for (lang, lang_code, pct, score) in details:
                    lang_code = lang_code.replace(' ','')
                    if lang_code != 'un':
                        pct = int(pct)
                        if pct > 0:
                            res = lang_code + ":" + str(pct)
                            lang_codes_with_pct.append(res)
                if len(lang_codes_with_pct) != 0:
                    result = ",".join(lang_codes_with_pct)
        except:
            pass
        return result

    # get_simhash() //field "C"
    #___________________________________________________________________________
    def get_simhash(self, record):

        result = '-'
        text_string = self.extracted_text
        if text_string is None:
            return result
        punct = '~`!@#$%^&*()-_=+[{]}|;:",<>./?\'\\'
        punct_spaces = ' ' * len(punct)
        punct_to_spaces = string.maketrans(punct, punct_spaces)
        try:
            text_string = text_string.strip().translate(punct_to_spaces)
            terms = text_string.decode('utf-8','ignore').lower().split()
            features = {k:sum(1 for _ in g) for k, g in groupby(sorted(terms))}
            result = str(Simhash(features).value)
        except:
            pass
        return result


    # get_file_name() //field "g"
    #___________________________________________________________________________
    def get_file_name(self, record):
        return self.warc_path


    # is_response()
    #___________________________________________________________________________
    def is_response(self, content_type):
        if content_type is None:
            return False

        got_match = False
        if self.response_pattern.match(content_type):
            got_match = True

        return got_match


    # get_new_style_checksum() //field "k"
    #___________________________________________________________________________
    def get_new_style_checksum(self, record):
        """Return a base32-encoded sha1
        For revisit records, return the original sha1
        """

        if 'revisit' == record.type:
            digest = record.get_header('WARC-Payload-Digest')
            if digest is None:
                return '-'
            else:
                return digest.replace('sha1:', '')
        elif 'response' == record.type and self.is_response(record.content_type):
            digest = record.get_header('WARC-Payload-Digest')
            #Our patched warc-tools fabricates this header if it is not present in the record
            return digest.replace('sha1:', '')
        elif 'response' == record.type and self.content is not None:
            # This is an arc record. Our patched warctools fabricates the WARC-Payload-Digest
            # header even for arc files so that we don't need to load large payloads in memory
            digest = record.get_header('WARC-Payload-Digest')
            if digest is not None:
                return digest.replace('sha1:', '')
            else:
                h = hashlib.sha1(self.content)
                return base64.b32encode(h.digest())
        else:
            h = hashlib.sha1(record.content[1])
            return base64.b32encode(h.digest())

    # get_mime_type() //field "m"
    #___________________________________________________________________________
    def get_mime_type(self, record, use_precalculated_value=True):
        """ See the WARC spec for more info on 'application/http; msgtype=response'
        http://archive-access.sourceforge.net/warc/warc_file_format-0.16.html#anchor7
        """

        if use_precalculated_value:
            return self.mime_type

        record_mime_type = '-'

        if self.is_response(record.content_type):
            record_mime_type = self.parse_http_content_type_header(record)

        if 'response' == record.type and record_mime_type != '-':
            mime_type = record_mime_type
        elif 'response' == record.type:
            if record.content_type is None:
                mime_type = 'unk'
            else:
                #alexa arc files use 'no-type' instead of 'unk'
                mime_type = record.content_type.replace('no-type', 'unk')
        elif 'warcinfo' == record.type:
            mime_type = 'warc-info'
        elif self.screenshot_mode and 'metadata' == record.type:
            mime_type = record.content[0]
        else:
            mime_type = record_mime_type

        try:
            mime_type = mime_type.decode('ascii')
        except (LookupError, UnicodeDecodeError):
            mime_type = u'unk'

        return mime_type


    # to_unicode()
    #___________________________________________________________________________
    @classmethod
    def to_unicode(self, s, charset):
        if isinstance(s, str):
            if charset is None:
                #try utf-8 and hope for the best
                s = s.decode('utf-8', 'replace')
            else:
                try:
                    s = s.decode(charset, 'replace')
                except LookupError:
                    s = s.decode('utf-8', 'replace')
        return s

    # urljoin_and_normalize()
    #___________________________________________________________________________
    @classmethod
    def urljoin_and_normalize(self, base, url, charset):
        """urlparse.urljoin removes blank fragments (trailing #),
        even if allow_fragments is set to True, so do this manually.

        Also, normalize /../ and /./ in url paths.

        Finally, encode spaces in the url with %20 so that we can
        later split on whitespace.

        Usage (run doctests with  `python -m doctest -v cdx_writer.py`):
        >>> base = 'http://archive.org/a/b/'
        >>> url  = '/c/d/../e/foo'
        >>> print CDX_Writer.urljoin_and_normalize(base, url, 'utf-8')
        http://archive.org/c/e/foo

        urljoin() doesn't normalize if the url starts with a slash, and
        os.path.normalize() has many issues, so normalize using regexes

        >>> url = '/foo/./bar/#'
        >>> print CDX_Writer.urljoin_and_normalize(base, url, 'utf-8')
        http://archive.org/foo/bar/#

        >>> base = 'http://archive.org'
        >>> url = '../site'
        >>> print CDX_Writer.urljoin_and_normalize(base, url, 'utf-8')
        http://archive.org/site

        >>> base = 'http://www.seomoz.org/page-strength/http://www.example.com/'
        >>> url  = 'http://www.seomoz.org/trifecta/fetch/page/http://www.example.com/'
        >>> print CDX_Writer.urljoin_and_normalize(base, url, 'utf-8')
        http://www.seomoz.org/trifecta/fetch/page/http://www.example.com/
        """

        url  = self.to_unicode(url, charset)

        #the base url is from the arc/warc header, which doesn't specify a charset
        base = self.to_unicode(base, 'utf-8')

        try:
            joined_url = urlparse.urljoin(base, url)
        except ValueError:
            #some urls we find in arc files no longer parse with python 2.7,
            #e.g. 'http://\x93\xe0\x90E\x83f\x81[\x83^\x93\xfc\x97\xcd.com/'
            return '-'

        # We were using os.path.normpath, but had to add too many patches
        # when it was doing the wrong thing, such as turning http:// into http:/
        m = re.match('(https?://.+?/)', joined_url)
        if m:
            domain = joined_url[:m.end(1)]
            path   = joined_url[m.end(1):]
            if path.startswith('../'):
                path = path[3:]
            norm_url = domain + re.sub('/[^/]+/\.\./', '/', path)
            norm_url = re.sub('/\./', '/', norm_url)
        else:
            norm_url = joined_url

        # deal with empty query strings and empty fragments, which
        # urljoin sometimes removes
        if url.endswith('?') and not norm_url.endswith('?'):
            norm_url += '?'
        elif url.endswith('#') and not norm_url.endswith('#'):
            norm_url += '#'

        #encode spaces
        return norm_url.replace(' ', '%20')


    # get_redirect() //field "r"
    #___________________________________________________________________________
    def get_redirect(self, record):
        """Aaron, Ilya, and Kenji have proposed using '-' in the redirect column
        unconditionally, after a discussion on Sept 5, 2012. It turns out the
        redirect column of the cdx has no effect on the Wayback Machine, and
        there were issues with parsing unescaped characters found in redirects.
        """
        return '-'

        # response_code = self.response_code
        #
        # ## It turns out that the refresh tag is being used in both 2xx and 3xx
        # ## responses, so always check both the http location header and the meta
        # ## tags. Also, the java version passes spaces through to the cdx file,
        # ## which might break tools that split cdx lines on whitespace.
        #
        # #only deal with 2xx and 3xx responses:
        # #if 3 != len(response_code):
        # #    return '-'
        #
        # charset = self.parse_charset()
        #
        # #if response_code.startswith('3'):
        # location = self.parse_http_header('location')
        # if location:
        #     return self.urljoin_and_normalize(record.url, location, charset)
        # #elif response_code.startswith('2'):
        # if self.meta_tags and 'refresh' in self.meta_tags:
        #     redir_loc = self.meta_tags['refresh']
        #     m = re.search('\d+\s*;\s*url=(.+)', redir_loc, re.I) #url might be capitalized
        #     if m:
        #         return self.urljoin_and_normalize(record.url, m.group(1), charset)
        #
        # return '-'

    # get_response_code() //field "s"
    #___________________________________________________________________________
    def get_response_code(self, record, use_precalculated_value=True):
        if use_precalculated_value:
            return self.response_code

        #if 'response' != record.type:
        #    return '-'

        m = re.match("HTTP(?:/\d\.\d)? (\d+)", record.content[1])
        if m:
            return m.group(1)
        else:
            return '-'

    # split_headers_and_content()
    #___________________________________________________________________________
    def parse_headers_and_content(self, record):
        """Returns a list of header lines, split with splitlines(), and the content.
        We call splitlines() here so we only split once, and so \r\n and \n are
        split in the same way.
        """

        if ('response' == record.type or 'revisit' == record.type) and record.content[1].startswith('HTTP'):
            try:
                headers, content = self.crlf_pattern.split(record.content[1], 1)
            except ValueError:
                headers = record.content[1]
                content = None
            headers = headers.splitlines()
        elif  self.screenshot_mode and 'metadata' == record.type:
            headers = None
            content = record.content[1]
        else:
            headers = None
            content = None

        return headers, content


    # should_exclude()
    #___________________________________________________________________________
    def should_exclude(self, surt_url):
        if not self.excludes:
            return False

        for prefix in self.excludes:
            if surt_url.startswith(prefix):
                return True

        return False


    # make_cdx()
    #___________________________________________________________________________
    def make_cdx(self):
        if isinstance(self.out_file, basestring):
            self.out_file = open(self.out_file, 'wb')
        self.out_file.write(' CDX ' + self.format + '\n') #print header

        if not self.all_records:
            #filter cdx lines if --all-records isn't specified
            allowed_record_types     = set(['response', 'revisit'])
            disallowed_content_types = set(['text/dns'])

        stats = {
            'num_records_processed': 0,
            'num_records_included':  0,
            'num_records_filtered':  0,
        }

        fh = ArchiveRecord.open_archive(self.file, gzip="auto", mode="r")
        for (offset, record, errors) in fh.read_records(limit=None, offsets=True):
            self.offset = offset

            if record:
                stats['num_records_processed'] += 1
                if self.screenshot_mode:
                    if record.type != 'metadata':
                        continue
                elif not self.all_records and (record.type not in allowed_record_types or record.content_type in disallowed_content_types):
                    continue

                ### arc files from the live web proxy can have a negative content length and a missing payload
                ### check the content_length from the arc header, not the computed payload size returned by record.content_length
                content_length_str = record.get_header(record.CONTENT_LENGTH)
                if content_length_str is not None and int(content_length_str) < 0:
                    continue

                self.surt = self.get_massaged_url(record, use_precalculated_value=False)
                if self.should_exclude(self.surt):
                    stats['num_records_filtered'] += 1
                    continue

                ### precalculated data that is used multiple times
                self.headers, self.content = self.parse_headers_and_content(record)
                self.mime_type             = self.get_mime_type(record, use_precalculated_value=False)
                self.response_code         = self.get_response_code(record, use_precalculated_value=False)
                self.meta_tags             = self.parse_meta_tags(record)

                if self.content_features:
                    ### parse out text
                    self.extracted_text        = self.extract_text(record)

                s = u''
                for field in self.format.split():
                    if not field in self.field_map:
                        raise ParseError('Unknown field: ' + field)

                    endpoint = self.field_map[field].replace(' ', '_')
                    response = getattr(self, 'get_' + endpoint)(record)
                    #print self.offset
                    #print record.compressed_record_size
                    #print record.content_length
                    #print record.headers
                    #print len(self.content)
                    #print repr(record.content[1])
                    #print endpoint
                    #print repr(response)
                    s += response + ' '
                self.out_file.write(s.rstrip().encode('utf-8')+'\n')
                #record.dump()
                stats['num_records_included'] += 1
            elif errors:
                raise ParseError(str(errors))
            else:
                pass # tail

        fh.close()

        if self.stats_file is not None:
            f = open(self.stats_file, 'w')
            json.dump(stats, f, indent=4)
            f.close()

# main()
#_______________________________________________________________________________
if __name__ == '__main__':

    parser = OptionParser(usage="%prog [options] warc.gz [output_file.cdx]")
    parser.set_defaults(format        = "N b a m s k r M S V g",
                        use_full_path = False,
                        file_prefix   = None,
                        all_records   = False,
                        screenshot_mode = False,
                        exclude_list    = None,
                        content_features = False,
                        canonicalizer_options = []
                       )

    parser.add_option("--format",  dest="format", help="A space-separated list of fields [default: '%default']")
    parser.add_option("--use-full-path", dest="use_full_path", action="store_true", help="Use the full path of the warc file in the 'g' field")
    parser.add_option("--file-prefix",   dest="file_prefix", help="Path prefix for warc file name in the 'g' field."
                      " Useful if you are going to relocate the warc.gz file after processing it."
                     )
    parser.add_option("--all-records",   dest="all_records", action="store_true", help="By default we only index http responses. Use this flag to index all WARC records in the file")
    parser.add_option("--screenshot-mode", dest="screenshot_mode", action="store_true", help="Special Wayback Machine mode for handling WARCs containing screenshots")
    parser.add_option("--exclude-list", dest="exclude_list", help="File containing url prefixes to exclude")
    parser.add_option("--stats-file", dest="stats_file", help="Output json file containing statistics")
    parser.add_option("--content-features", dest="content_features", action="store_true", help="Add content feature fields to the end of the CDX line")
    parser.add_option("--no-host-massage", dest="canonicalizer_options",
                      action='append_const', const=('host_massage', False),
                      help='Turn off host_massage (ex. stripping "www.")')

    (options, input_files) = parser.parse_args(args=sys.argv[1:])

    if len(input_files) != 2:
        if len(input_files) == 1:
            input_files.append(sys.stdout)
        else:
            parser.print_help()
            exit(-1)

    #enable content features through flag
    if options.content_features:
        if 'Q' not in options.format:
            options.format = options.format + " Q"
        if 'C' not in options.format:
            options.format = options.format + " C"

    #enable content features through format
    if 'Q' in options.format or 'C' in options.format:
        options.content_features = True

    if options.content_features:
        if content_features_disabled:
            print("Unable to import libraries needed to extract content based features!")
            exit(-1)
        # set memory limits on content feature extraction
        soft_limit = 800 * 1000000
        hard_limit = 900 * 1000000
        resource.setrlimit(resource.RLIMIT_AS, (soft_limit, hard_limit))

    cdx_writer = CDX_Writer(input_files[0], input_files[1],
                            format                = options.format,
                            use_full_path         = options.use_full_path,
                            file_prefix           = options.file_prefix,
                            all_records           = options.all_records,
                            screenshot_mode       = options.screenshot_mode,
                            exclude_list          = options.exclude_list,
                            stats_file            = options.stats_file,
                            content_features      = options.content_features,
                            canonicalizer_options = options.canonicalizer_options
                           )
    cdx_writer.make_cdx()
