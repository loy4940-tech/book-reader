"""Phase 8Aで発生する明示的な処理エラー。"""


class OcrPageError(Exception):
    """ページ処理に失敗したstageを保持する基底例外。"""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


class InputImageError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("input", message)


class ClassifierError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("classifier", message)


class PreprocessError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("preprocess", message)


class EngineUnavailableError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("engine_unavailable", message)


class EngineProcessError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("engine_process", message)


class RecordAssemblyError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("record_assembly", message)


class FigurePersistenceError(OcrPageError):
    def __init__(self, message: str) -> None:
        super().__init__("figure_persistence", message)
