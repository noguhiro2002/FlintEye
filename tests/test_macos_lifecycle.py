import sys
import tempfile
import unittest
from pathlib import Path
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

    @unittest.skipUnless(sys.platform == 'darwin', 'Requires the native NSStatusItem menu')
    def test_status_menu_dispatches_retry_and_confirmed_force_quit(self):
        import pystray
        from PyObjCTools.AppHelper import callLater
        from flinteye_app.flinteye_desktop import DesktopActions, _run_tray

        snapshot = {'label': 'Finishing recordings', 'message': 'Retry the recording stop.',
                    'counts': {'receiving':0, 'targets':4, 'recording':0}, 'pending_segments':4,
                    'state': 'finalizing', 'phase': 'finalizing', 'color': 'amber', 'busy':False,
                    'controls': {'start':False, 'stop':True, 'restart':False, 'retry_stop':True}}
        controller = Mock()
        controller.status.return_value = snapshot
        controller.perform.return_value = {'ok':False, 'message':'still waiting'}
        server = SimpleNamespace(should_exit=False)
        actions = DesktopActions(controller, server)
        real_icon = pystray.Icon
        icons, failures = [], []

        def create_icon(*args, **kwargs):
            icon = real_icon(*args, **kwargs)
            icons.append(icon)
            return icon

        def click(title):
            menu = icons[0]._menu_handle[0]
            index = menu.indexOfItemWithTitle_(title)
            self.assertGreaterEqual(index, 0)
            self.assertTrue(menu.itemAtIndex_(index).isEnabled())
            menu.performActionForItemAtIndex_(index)

        def drive(step=0):
            try:
                if step == 0:
                    menu = icons[0]._menu_handle[0]
                    start = menu.itemWithTitle_('Start monitoring')
                    self.assertIsNotNone(start)
                    self.assertFalse(start.isEnabled())
                    click('Retry Stop')
                elif step == 1:
                    controller.perform.assert_called_once_with('stop')
                    click('Force quit (recordings may be incomplete)')
                elif step == 2:
                    self.assertFalse(server.should_exit)
                    controller.request_force_quit.assert_not_called()
                    click('Force quit (recordings may be incomplete)')
                else:
                    self.assertTrue(server.should_exit)
                    return
                callLater(.25, drive, step+1)
            except Exception as error:
                failures.append(error)
                server.should_exit = True

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(pystray, 'Icon', side_effect=create_icon), \
             patch('flinteye_app.cli.autostart_status', return_value={'enabled':True,'available':True}), \
             patch('flinteye_app.flinteye_desktop._confirm_force_quit', side_effect=[False, True]) as confirm:
            callLater(1, drive)
            _run_tray(server, Path(directory), controller, actions, Mock())
        if failures:
            raise failures[0]
        self.assertEqual(confirm.call_count, 2)
        controller.request_force_quit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
