"""Entry point for the MotionJoy Tracking Generator."""

from __future__ import annotations

import logging

from ui import App


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
