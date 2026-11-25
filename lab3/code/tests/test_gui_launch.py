"""Guard the launch behavior that should open the graphical app by default."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, sentinel

from campus_market import entry, webapp


class StoppedServer:
    """A server stopped immediately by the user, without opening any socket."""

    base_url = "http://127.0.0.1:48123"

    def __init__(self):
        self.closed = False
        self.poll_interval = None

    def serve_forever(self, poll_interval):
        self.poll_interval = poll_interval
        raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


class GraphicalLaunchTests(unittest.TestCase):
    def run_launch(self, extra_arguments=()):
        server = StoppedServer()
        directory = Path("/unused/test-only-demo")
        credentials = {"buyer": {"identifier": "fictional", "password": "test-only"}}
        with (
            patch(
                "campus_market.web_seed.prepare_demo", return_value=(sentinel.market, credentials)
            ) as prepare,
            patch("campus_market.webapp.MarketHTTPServer", return_value=server) as factory,
            patch("campus_market.webapp.webbrowser.open") as open_browser,
            redirect_stdout(io.StringIO()),
        ):
            result = webapp.main(["--demo", "--data-dir", str(directory), *extra_arguments])
            prepare.assert_called_once_with(directory)
            factory.assert_called_once_with(("127.0.0.1", 0), sentinel.market, credentials)
            self.assertEqual(result, 0)
            self.assertTrue(server.closed)
            self.assertIsNotNone(server.poll_interval)
            return open_browser.call_args_list

    def test_demo_launch_opens_browser_and_closes_server_on_interrupt(self):
        calls = self.run_launch()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, (StoppedServer.base_url,))

    def test_no_browser_launch_preserves_explicit_headless_option(self):
        self.assertEqual(self.run_launch(["--no-browser"]), [])

    def test_shared_entry_forwards_gui_arguments_without_changing_them(self):
        arguments = ["gui", "--demo", "--data-dir", "带 空格的目录", "--no-browser"]
        original = list(arguments)
        with patch("campus_market.webapp.main", return_value=7) as gui_main:
            self.assertEqual(entry.main(arguments), 7)
            gui_main.assert_called_once_with(arguments[1:])
        self.assertEqual(arguments, original)

    def test_shared_entry_preserves_existing_cli_commands_and_return_code(self):
        arguments = ["--guest", "products", "--keyword", "教材"]
        with patch("campus_market.cli.main", return_value=3) as cli_main:
            self.assertEqual(entry.main(arguments), 3)
            cli_main.assert_called_once_with(arguments)
