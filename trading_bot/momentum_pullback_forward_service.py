from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)
from .webull_tick_recorder_service import (
    WebullTickRecorderService,
)


@dataclass(frozen=True)
class MomentumForwardSelection:
    selected_symbols: tuple[str, ...]
    rejected_symbols: tuple[str, ...]


class MomentumPullbackForwardService:
    """
    Research-only coordinator.

    Flow:
      scanner snapshots
      -> top eligible Momentum Pullback names
      -> Webull tick recorder
      -> local 10-second history

    No order submission or broker actions are used.
    """

    def __init__(
        self,
        *,
        scanner: MomentumPullbackScanner,
        app_key: str,
        app_secret: str,
        output_root: str = "data/webull_10s",
    ) -> None:
        self.scanner = scanner
        self.app_key = app_key
        self.app_secret = app_secret
        self.output_root = output_root

    def select_symbols(
        self,
        snapshots: Iterable[
            MomentumStockSnapshot
        ],
    ) -> MomentumForwardSelection:
        snapshots = list(snapshots)

        selected = (
            self.scanner.select_candidates(
                snapshots
            )
        )

        selected_symbols = tuple(
            snapshot.symbol
            for snapshot in selected
        )

        selected_set = set(
            selected_symbols
        )

        rejected_symbols = tuple(
            snapshot.symbol
            for snapshot in snapshots
            if snapshot.symbol
            not in selected_set
        )

        return MomentumForwardSelection(
            selected_symbols=selected_symbols,
            rejected_symbols=rejected_symbols,
        )

    def build_recorder(
        self,
        *,
        snapshots: Iterable[
            MomentumStockSnapshot
        ],
    ) -> WebullTickRecorderService:
        selection = self.select_symbols(
            snapshots
        )

        if not selection.selected_symbols:
            raise ValueError(
                "No Momentum Pullback symbols "
                "qualified for recording."
            )

        return WebullTickRecorderService(
            symbols=(
                selection.selected_symbols
            ),
            app_key=self.app_key,
            app_secret=self.app_secret,
            output_root=self.output_root,
        )
