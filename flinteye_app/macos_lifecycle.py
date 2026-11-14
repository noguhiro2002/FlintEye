"""Route Cocoa Quit through Python cleanup instead of NSApplication's exit()."""
from contextlib import contextmanager

_delegate_class = None


@contextmanager
def graceful_application_quit(icon, server):
    import AppKit
    import Foundation
    import objc

    global _delegate_class
    if _delegate_class is None:
        class FlintEyeTerminationDelegate(Foundation.NSObject):
            # NSApplicationTerminateReply is NSUInteger on supported 64-bit Macs.
            @objc.signature(b'Q@:@')
            def applicationShouldTerminate_(self, application):
                self.server.should_exit = True
                self.icon.stop()
                # Cancel Cocoa's immediate process exit. icon.stop() returns
                # control to cli.main(), which stops and reaps media children.
                return AppKit.NSTerminateCancel
        _delegate_class = FlintEyeTerminationDelegate

    application = AppKit.NSApplication.sharedApplication()
    previous = application.delegate()
    delegate = _delegate_class.alloc().init()
    delegate.icon, delegate.server = icon, server
    application.setDelegate_(delegate)
    try:
        yield
    finally:
        application.setDelegate_(previous)

