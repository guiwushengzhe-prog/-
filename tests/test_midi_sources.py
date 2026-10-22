import io
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from piano import midi_sources as sources
except ImportError:
    import midi_sources as sources

VALID_MIDI = b'MThd' + struct.pack('>IHHH', 6, 0, 1, 480) + b'MTrk' + struct.pack('>I', 4) + b'\x00\xff\x2f\x00'
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
HTML = b'''<table class="table-bordered result-table">
<tr><td>F&#252;r Elise</td><td>by L. V. Beethoven (1770-1827)</td><td>WoO 59</td><td></td></tr>
<tr><td>for Piano</td><td>1810</td><td>Classical</td><td></td></tr>
<tr><td>Source</td><td><a href="../legal.html#publicdomain">Public Domain</a></td>
<td><a href="piece-info.cgi?id=931">More Information</a></td><td>2015</td></tr>
<tr><td><a href="https://www.mutopiaproject.org/ftp/example.mid">.mid file</a></td></tr></table>'''


class MidiSourcesTests(unittest.TestCase):
    def setUp(self):
        for name in ('_ichigo_search', '_eightnotes_search', '_midiworld_search', '_collection_search'):
            provider = patch.object(sources, name, return_value=[])
            provider.start()
            self.addCleanup(provider.stop)

    def test_chinese_aliases_translate_queries_not_results(self):
        terms, used = sources._query_variants('贝多芬 致爱丽丝')
        self.assertEqual(terms, ['Beethoven Fur Elise'])
        self.assertEqual(set(used), {'贝多芬', '致爱丽丝'})

    def test_real_provider_layout_preserves_edition_and_license(self):
        url = 'https://www.mutopiaproject.org/cgibin/make-table.cgi?searchingfor=Fur+Elise'
        with patch.object(sources, '_fetch', return_value=(HTML, url)):
            found = sources.search('致爱丽丝')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['title'], 'Für Elise')
        self.assertEqual(found[0]['license'], 'Public Domain')
        self.assertEqual(found[0]['title_similarity'], 1.0)
        self.assertTrue(found[0]['piano_solo'])
        self.assertIn('id=931', found[0]['page_url'])

    def test_composer_name_alone_is_not_a_song_match(self):
        similarity = sources._title_similarity('Beethoven', 'Für Elise', 'WoO 59', 'L. V. Beethoven')
        self.assertEqual(similarity, 0)

    def test_generic_form_is_not_a_unique_song_identity(self):
        self.assertLess(sources._title_similarity('Canon', 'Canon alla Ottava', 'BWV 1080', 'Bach'), .62)

    def test_pachelbel_alias_does_not_download_an_unrelated_bach_canon(self):
        other = HTML.replace(b'F&#252;r Elise', b'Canon alla Ottava').replace(b'L. V. Beethoven', b'J. S. Bach')
        url = 'https://www.mutopiaproject.org/cgibin/make-table.cgi?searchingfor=Canon'
        with patch.object(sources, '_fetch', return_value=(other, url)) as fetch:
            found = sources.search('卡农')
            self.assertTrue(found)
            self.assertLess(found[0]['match_score'], .70)
            with self.assertRaises(sources.MidiSourceError):
                sources.download_best('卡农', ROOT / 'unused')
        # Both calls fetched search pages only; no candidate MIDI was requested.
        self.assertTrue(all('make-table.cgi?' in call.args[0] for call in fetch.call_args_list))

    def test_non_provider_urls_are_blocked_before_dns(self):
        with patch.object(sources.socket, 'getaddrinfo') as dns:
            for url in ('http://www.mutopiaproject.org/a.mid', 'https://127.0.0.1/a.mid',
                        'https://localhost/a.mid', 'file:///tmp/a.mid',
                        'https://www.mutopiaproject.org:8443/a.mid',
                        'https://user@www.mutopiaproject.org/a.mid',
                        'https://www.mutopiaproject.org.evil.example/a.mid'):
                with self.subTest(url=url), self.assertRaises(sources.MidiSourceError):
                    sources._validate_url(url)
            dns.assert_not_called()

    def test_allowed_hostname_resolving_private_address_is_blocked(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.10', 443))]
        with patch.object(sources.socket, 'getaddrinfo', return_value=private):
            with self.assertRaises(sources.MidiSourceError):
                sources._validate_url('https://www.mutopiaproject.org/a.mid')

    def test_redirect_to_private_url_is_never_requested(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://www.mutopiaproject.org/a.mid', 302, 'Found',
                                           {'Location': 'https://127.0.0.1/secret'}, None)
        with patch.object(sources, 'build_opener', return_value=opener), \
                patch.object(sources.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            with self.assertRaises(sources.MidiSourceError):
                sources._fetch('https://www.mutopiaproject.org/a.mid', sources.MAX_MIDI_BYTES)
        self.assertEqual(opener.open.call_count, 1)

    def test_declared_oversize_response_is_not_read(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {'Content-Length': str(sources.MAX_MIDI_BYTES + 1)}
        opener = Mock()
        opener.open.return_value = response
        with patch.object(sources, 'build_opener', return_value=opener), \
                patch.object(sources.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            with self.assertRaises(sources.MidiSourceError):
                sources._fetch('https://www.mutopiaproject.org/a.mid', sources.MAX_MIDI_BYTES)
        response.read.assert_not_called()

    def test_chunked_response_has_read_limit(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {}
        response.read.return_value = b'x' * (sources.MAX_MIDI_BYTES + 1)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(sources, 'build_opener', return_value=opener), \
                patch.object(sources.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            with self.assertRaises(sources.MidiSourceError):
                sources._fetch('https://www.mutopiaproject.org/a.mid', sources.MAX_MIDI_BYTES)
        response.read.assert_called_once_with(sources.MAX_MIDI_BYTES + 1)

    def test_midi_header_and_track_lengths_are_validated(self):
        self.assertEqual(sources._validate_midi(VALID_MIDI)['format'], 0)
        for data in (b'<html>login</html>', b'MThd', VALID_MIDI[:-1], b'MThd' + b'x' * 100):
            with self.subTest(data=data[:14]), self.assertRaises(sources.MidiSourceError):
                sources._validate_midi(data)

    def test_low_relevance_result_is_not_downloaded(self):
        candidate = {'piano_solo': True, 'title_similarity': .2, 'match_score': .3}
        with patch.object(sources, 'search', return_value=[candidate]), patch.object(sources, '_fetch') as fetch:
            with self.assertRaises(sources.MidiSourceError):
                sources.download_best('a different song', ROOT / 'unused')
            fetch.assert_not_called()

    def test_missing_song_does_not_produce_fallback_notes(self):
        with patch.object(sources, '_mutopia_search', return_value=[]):
            self.assertEqual(sources.search('NoSuchSong987654321'), [])
            with self.assertRaises(sources.MidiSourceError):
                sources.download_best('NoSuchSong987654321', ROOT / 'unused')

    def test_successful_download_is_midi_only_and_preserves_provenance(self):
        candidate = {'title': 'Für Elise', 'composer': 'Beethoven', 'provider': 'Mutopia Project',
                     'license': 'Public Domain', 'page_url': 'https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931',
                     'midi_url': 'https://www.mutopiaproject.org/ftp/elise.mid',
                     'piano_solo': True, 'title_similarity': 1., 'match_score': .98}
        messages = []
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sources, 'search', return_value=[candidate]), \
                patch.object(sources, '_fetch', return_value=(VALID_MIDI, candidate['midi_url'])):
            result = sources.download_best('致爱丽丝', directory, messages.append)
            self.assertEqual(result['path'].read_bytes(), VALID_MIDI)
            self.assertEqual(result['license'], 'Public Domain')
            self.assertEqual(result['page_url'], candidate['page_url'])
            self.assertEqual(result['midi_header']['tracks'], 1)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertTrue(messages)


class ExpandedCatalogTests(unittest.TestCase):
    def test_local_title_matches_translated_names(self):
        for query in ('summer', '菊次郎的夏天', '菊次郎之夏', '久石让 Summer'):
            self.assertTrue(sources.matches_local_title(query, '久石譲 - Summer'), query)
            self.assertTrue(sources.matches_local_title(query, 'Summer'), query)
        self.assertFalse(sources.matches_local_title('Summer', 'Madoka Summer Time'))
        self.assertFalse(sources.matches_local_title('菊次郎的夏天', 'Night Cruising'))

    def test_anime_catalog_uses_real_midi_link_and_solo_instrument(self):
        html = '''<span class="title2"><a href="/sheets/374">Kikujiro</a></span><br><br>
Summer (full version) (Transcribed by illinattta)<br><i>for Piano</i> |
<a href="/res/getfile.php?id=4645&type=midi&token=current">midi</a> | <br><br>
Summer (Transcribed by someone)<br><i>for Piano and Flute</i> |
<a href="/res/getfile.php?id=999&type=midi&token=other">midi</a>'''.encode()
        with patch.object(sources, '_fetch', return_value=(html, 'https://ichigos.com/sheets')) as fetch:
            result = sources._ichigo_search('Summer', ['Summer'], ['菊次郎的夏天'], '菊次郎的夏天')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'Summer (full version)')
        self.assertEqual(result[0]['work'], 'Kikujiro')
        self.assertEqual(result[0]['composer'], 'Joe Hisaishi')
        self.assertEqual(result[0]['page_url'], 'https://ichigos.com/sheets/374')
        self.assertIn('token=current', result[0]['midi_url'])
        self.assertIn(b'qtitle=Summer', fetch.call_args.args[2])

    def test_canon_alias_accepts_named_work_but_not_bach_or_rock(self):
        terms, _ = sources._query_variants('卡农')
        self.assertIn('Canon in D', terms)
        self.assertIn('Canon', terms)
        self.assertGreater(sources._canonical_similarity('Canon', 'Canon in D', '', 'Pachelbel', '卡农'), .9)
        self.assertLess(sources._canonical_similarity('Canon', 'Canon alla Ottava', '', 'Bach', '卡农'), .62)
        self.assertLess(sources._canonical_similarity('Canon', 'Canon Rock', '', 'Jerry C', '卡农'), .62)
        self.assertTrue(sources.matches_local_title('卡农', 'Canon in D (long version)'))
        self.assertFalse(sources.matches_local_title('卡农', 'Bach Canon in D BWV 1072'))

    def test_eightnotes_queries_piano_and_reads_public_midi_link(self):
        html = b'''<table><tr onclick="document.location='/scores/7351.asp'">
<td class="artname">Pachelbel</td><td class="fsmtitle">Canon in D (long version)</td>
<td class="level_type ditchit">Piano</td></tr>
<tr onclick="document.location='/scores/7393.asp'"><td class="artname">Pachelbel</td>
<td class="fsmtitle">Canon in D</td><td class="level_type">Flute</td></tr></table>'''
        score = b'<a href="https://media.8notes.com/school/midi/piano/pachelbel_canon_d.mid">Download Midi File</a>'
        with patch.object(sources, '_fetch', side_effect=[(html, 'https://www.8notes.com/search'),
                                                         (score, 'https://www.8notes.com/scores/7351.asp')]) as fetch:
            result = sources._eightnotes_search('Canon in D', ['Canon in D'], ['卡农'], '卡农')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['composer'], 'Pachelbel')
        self.assertTrue(result[0]['piano_solo'])
        self.assertIn('pachelbel_canon_d.mid', result[0]['midi_url'])
        self.assertIn('keyword=Canon+in+D+piano', fetch.call_args_list[0].args[0])
        self.assertEqual(fetch.call_count, 2)

    def test_general_archives_preserve_song_and_composer_and_require_instrument_check(self):
        world = b'''<li>Canon in E flat (Easy Version) (Johann Pachelbel) -
<a href="https://www.midiworld.com/download/4573">download</a><script>ignore()</script></li>
<li>Canon rock (Jerry C) - <a href="https://www.midiworld.com/download/5732">download</a></li>'''
        collection = b'''<tr data-midi-id="24402" data-title="pachelbels-canon-arranged" data-artist="">
<td><button class="midi-play-btn" data-url="/midi/MIDI/pachelbels-canon-arranged.mid">Play</button></td>
<td class="title-cell"><a href="/song/24402/pachelbels-canon-arranged">Canon</a></td></tr>'''
        with patch.object(sources, '_fetch', return_value=(world, 'https://www.midiworld.com/search/?q=canon')):
            result = sources._midiworld_search('Canon', ['Canon in D'], ['卡农'], '卡农')
        self.assertEqual(result[0]['composer'], 'Johann Pachelbel')
        self.assertTrue(result[0]['requires_piano_check'])
        self.assertFalse(result[0]['piano_solo'])
        self.assertGreater(result[0]['match_score'], .7)
        self.assertLess(result[1]['match_score'], .7)
        with patch.object(sources, '_fetch', return_value=(collection, 'https://midicollection.com/search')) as fetch:
            result = sources._collection_search('Pachelbel', ['Canon in D'], ['卡农'], '卡农')
        self.assertEqual(result[0]['title'], 'pachelbels-canon-arranged')
        self.assertEqual(result[0]['page_url'], 'https://midicollection.com/song/24402/pachelbels-canon-arranged')
        self.assertIn(b'search=Pachelbel', fetch.call_args.args[2])

    def test_archive_download_skips_band_instruments_and_tries_another_source(self):
        import mido

        def midi_bytes(program):
            midi = mido.MidiFile()
            track = mido.MidiTrack([
                mido.Message('program_change', program=program),
                mido.Message('note_on', note=60, velocity=80),
                mido.Message('note_off', note=60, time=480),
            ])
            midi.tracks.append(track)
            buffer = io.BytesIO()
            midi.save(file=buffer)
            return buffer.getvalue()

        piano, strings = midi_bytes(0), midi_bytes(48)
        with self.assertRaises(sources.MidiSourceError):
            sources._validate_piano(strings)
        self.assertEqual(sources._validate_piano(piano)['piano_notes'], 1)
        first = sources._catalog_candidate('Canon in D', 'Pachelbel', 'MIDI Collection',
                    'https://midicollection.com/song/1/canon', 'https://midicollection.com/midi/a.mid',
                    ['Canon in D'], ['卡农'], '卡农')
        second = {**first, 'provider': '8notes', 'midi_url': 'https://media.8notes.com/piano.mid'}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sources, 'search', return_value=[first, second]), \
                patch.object(sources, '_fetch', side_effect=[(strings, first['midi_url']), (piano, second['midi_url'])]):
            found = sources.download_best('卡农', directory)
            self.assertEqual(found['provider'], '8notes')
            self.assertTrue(found['piano_solo'])
            self.assertEqual(found['path'].read_bytes(), piano)

    def test_success_in_first_source_does_not_hide_other_sources(self):
        candidate = sources._catalog_candidate('Canon in D', 'Pachelbel', '8notes',
                    'https://www.8notes.com/scores/7351.asp', 'https://media.8notes.com/canon.mid',
                    ['Canon in D'], ['卡农'], '卡农', solo=True)
        with patch.object(sources, '_ichigo_search', return_value=[candidate]), \
                patch.object(sources, '_mutopia_search', return_value=[]) as classical, \
                patch.object(sources, '_eightnotes_search', return_value=[]) as notes, \
                patch.object(sources, '_midiworld_search', return_value=[]) as world, \
                patch.object(sources, '_collection_search', return_value=[]) as collection:
            self.assertEqual(len(sources.search('卡农')), 1)
        for provider in (classical, notes, world, collection):
            self.assertTrue(provider.called)


if __name__ == '__main__':
    unittest.main()
