"""The start-up check for a newer version: what it asks, what it believes, and how quietly it fails."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import update  # noqa: E402


def answering(payload, seen=None):
    """A stand-in for the internet that answers every request with ``payload``."""
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def opener(request, timeout=None):
        if seen is not None:
            seen.append((request.full_url, dict(request.header_items()), timeout))
        return Response(payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8'))
    return opener


def release(tag, **more):
    return {'tag_name': tag, 'html_url': f'{update.REPOSITORY}/releases/tag/{tag}', **more}


class TestVersionNumbers:
    def test_later_numbers_are_newer(self):
        assert update.is_newer('2.7.0', '2.6.0') and update.is_newer('v2.10.0', '2.9.3')
        assert update.is_newer('3.0', '2.99.99') and update.is_newer('2.6.1', '2.6')

    def test_the_same_or_older_is_not(self):
        assert not update.is_newer('2.6.0', '2.6.0') and not update.is_newer('2.6', '2.6.0')
        assert not update.is_newer('2.5.9', '2.6.0')

    def test_anything_that_is_not_a_number_is_never_an_update(self):
        for odd in ('', 'latest', '2.7.0-beta', '2.7.0 && calc', None):
            assert not update.is_newer(odd, '2.6.0'), odd
        assert not update.is_newer('2.7.0', '')


class TestTheInstalledVersion:
    def test_it_is_read_from_the_package_record(self, tmp_path):
        (tmp_path / 'RELEASE.json').write_text(json.dumps({'version': '2.7.0'}), encoding='utf-8')
        assert update.installed_version(tmp_path) == '2.7.0'

    def test_a_development_folder_has_none(self, tmp_path):
        assert update.installed_version(tmp_path) == ''
        (tmp_path / 'RELEASE.json').write_text('not json', encoding='utf-8')
        assert update.installed_version(tmp_path) == ''


class TestAsking:
    def test_a_newer_release_is_reported_with_its_page(self):
        seen = []
        found = update.available_update('2.6.0', opener=answering(release('v2.7.0'), seen))
        assert found == ('2.7.0', f'{update.REPOSITORY}/releases/tag/v2.7.0')
        address, _headers, timeout = seen[0]
        assert address == update.LATEST and timeout, 'one request, to the project, that cannot hang the app'
        assert '?' not in address, 'nothing about this PC goes in the address'

    def test_the_same_version_says_nothing(self):
        assert update.available_update('2.7.0', opener=answering(release('v2.7.0'))) is None

    def test_a_development_folder_never_asks(self):
        def no_internet(*_, **__):
            raise AssertionError('asked the internet')
        assert update.available_update('', opener=no_internet) is None

    def test_drafts_and_previews_are_not_offered(self):
        assert update.available_update('2.6.0', opener=answering(release('v2.7.0', draft=True))) is None
        assert update.available_update('2.6.0', opener=answering(release('v2.7.0', prerelease=True))) is None

    def test_being_offline_or_answered_with_nonsense_is_silent(self):
        def offline(*_, **__):
            raise OSError('no route to host')
        assert update.available_update('2.6.0', opener=offline) is None
        for nonsense in (b'<html>rate limited</html>', b'[]', b'{}', json.dumps({'tag_name': 'nightly'}).encode()):
            assert update.available_update('2.6.0', opener=answering(nonsense)) is None

    def test_the_button_only_ever_opens_the_projects_own_pages(self):
        elsewhere = {'tag_name': 'v9.0.0', 'html_url': 'https://example.com/get-it-here'}
        assert update.available_update('2.6.0', opener=answering(elsewhere)) == ('9.0.0', update.DOWNLOAD_PAGE)
        lookalike = {'tag_name': 'v9.0.0', 'html_url': update.REPOSITORY + '-fake/releases/tag/v9.0.0'}
        assert update.available_update('2.6.0', opener=answering(lookalike))[1] == update.DOWNLOAD_PAGE


class TestAskingByHand:
    def test_each_of_the_three_answers(self):
        def offline(*_, **__):
            raise OSError('no route to host')
        assert update.check('2.6.0', opener=answering(release('v2.7.0')))[:2] == (update.NEWER, '2.7.0')
        assert update.check('2.7.0', opener=answering(release('v2.7.0'))) == (update.LATEST_INSTALLED, '2.7.0', '')
        assert update.check('2.7.0', opener=offline) == (update.UNKNOWN, '', '')
        assert update.check('', opener=answering(release('v2.7.0'))) == (update.UNKNOWN, '', '')


class TestThePrivacyCheckAllowsOnlyTheseAddresses:
    """The package builder refuses private strings. The addresses the update check asks are the one exception."""

    def scan(self, tmp_path, words):
        import pytest
        sys.path.insert(0, str(ROOT / 'release'))
        import privacy
        if not privacy.LOCAL_PATTERNS.is_file():
            pytest.skip('the private patterns are not on this machine')
        (tmp_path / 'sample.py').write_text(words, encoding='utf-8')
        return privacy, privacy.findings([tmp_path / 'sample.py'], root=tmp_path)

    def test_the_addresses_the_app_asks_are_the_ones_allowed(self, tmp_path):
        privacy, found = self.scan(tmp_path, f'{update.REPOSITORY}/releases/latest\n{update.LATEST}\n')
        assert set(privacy.PUBLISHED) == {update.REPOSITORY, update.LATEST.rsplit('/releases/', 1)[0]}
        assert not found

    def test_the_same_account_anywhere_else_is_still_refused(self, tmp_path):
        account = update.REPOSITORY.rsplit('/', 1)[0]
        _privacy, found = self.scan(tmp_path, f'{account}/something-else\n')
        assert found, 'only the exact addresses pass, not the name inside them'
