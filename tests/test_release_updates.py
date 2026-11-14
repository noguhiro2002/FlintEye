import unittest

from flinteye_app.release_updates import release_key, update_result


def published(tag, **kwargs):
    return {'tag_name': tag, 'draft': False, 'prerelease': '-preview.' in tag, **kwargs}


class ReleaseUpdateTests(unittest.TestCase):
    def result(self, releases, current='1.1.2-preview.1', channel='preview'):
        return update_result(releases, current=current.split('-')[0], current_release=current, channel=channel)

    def test_preview_numbers_are_compared_numerically_and_final_sorts_after_preview(self):
        result = self.result([published('v1.1.2-preview.2'), published('v1.1.2-preview.10')])
        self.assertTrue(result['available'])
        self.assertEqual(result['version'], 'v1.1.2-preview.10')
        self.assertGreater(release_key('1.1.2'), release_key('1.1.2-preview.999'))
        self.assertFalse(self.result([published('v1.1.2-preview.1')])['available'])

    def test_stable_channel_never_offers_preview(self):
        result = self.result([published('v1.1.3-preview.1'), published('v1.1.2')], '1.1.2', 'stable')
        self.assertFalse(result['available'])
        self.assertEqual(result['version'], 'v1.1.2')
        self.assertTrue(self.result([published('v1.1.2')])['available'])

    def test_drafts_invalid_tags_and_wrong_github_status_are_ignored(self):
        result = self.result([published('v9.0.0', draft=True), published('v9.0.1-preview.1', prerelease=False),
                              published('v9.0.2', prerelease=True), published('v9.0.3/evil'),
                              published('v9.0.3-preview.0'), {'tag_name': None}])
        self.assertFalse(result['available'])
        self.assertNotIn('version', result)

    def test_links_are_derived_from_validated_tag_not_remote_html_url(self):
        result = self.result([published('v1.1.3-preview.1', html_url='https://example.test/evil')])
        self.assertEqual(result['url'], 'https://github.com/noguhiro2002/FlintEye/releases/tag/v1.1.3-preview.1')

    def test_source_snapshot_does_not_advertise_installer_updates(self):
        result = self.result([published('v9.0.0')], '1.1.1', 'source')
        self.assertFalse(result['available'])
        self.assertIn('Source checkout', result['message'])
