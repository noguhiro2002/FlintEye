import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flinteye_app import macos_lifecycle
from flinteye_app.desktop_icon import apply_application_icon


class MacQuitTests(unittest.TestCase):
    def test_native_dialog_restores_the_running_application_icon(self):
        image, application = Mock(), Mock()
        appkit = SimpleNamespace(NSImage=Mock(), NSApplication=Mock())
        appkit.NSImage.alloc.return_value.initWithContentsOfFile_.return_value = image
        appkit.NSApplication.sharedApplication.return_value = application
        with patch.dict(sys.modules, {'AppKit': appkit}), patch('sys.platform', 'darwin'):
            apply_application_icon()
        application.setApplicationIconImage_.assert_called_once_with(image)
        self.assertTrue(appkit.NSImage.alloc.return_value.initWithContentsOfFile_.call_args.args[0].endswith('flinteye.icns'))

    def check_quit(self, appkit):
        application = appkit.NSApplication.sharedApplication()
        previous = application.delegate()
        icon, server = Mock(), SimpleNamespace(should_exit=False)
        with macos_lifecycle.graceful_application_quit(icon, server):
            reply = application.delegate().applicationShouldTerminate_(application)
            self.assertEqual(reply, appkit.NSTerminateCancel)
            self.assertTrue(server.should_exit)
            icon.stop.assert_called_once()
        self.assertEqual(application.delegate(), previous)

    def test_quit_delegates_cleanup_instead_of_immediate_exit(self):
        class NSObject:
            @classmethod
            def alloc(cls): return cls()
            def init(self): return self
        application = SimpleNamespace(current=object())
        application.delegate = lambda: application.current
        application.setDelegate_ = lambda value: setattr(application, 'current', value)
        appkit = SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda: application), NSTerminateCancel=0)
        modules = {'AppKit':appkit, 'Foundation':SimpleNamespace(NSObject=NSObject),
                   'objc':SimpleNamespace(signature=lambda signature: lambda method: method)}
        with patch.dict(sys.modules, modules), patch.object(macos_lifecycle, '_delegate_class', None):
            self.check_quit(appkit)

    @unittest.skipUnless(sys.platform == 'darwin', 'Requires native AppKit/PyObjC')
    def test_native_cocoa_quit_delegate(self):
        import AppKit
        self.check_quit(AppKit)


if __name__ == '__main__':
    unittest.main()
