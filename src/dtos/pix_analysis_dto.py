from copy import deepcopy

from models import PixAnalysis


class PixAnalysisDTO:
    """O que chega ao cliente: a análise nos três campos do desafio.

    O mesmo envelope sai do POST e do GET: `key`, `status` e `metadata`. O id
    interno da tabela e as colunas de auditoria nunca saem daqui.
    """

    @staticmethod
    def obj_to_dict(pix_analysis: PixAnalysis) -> dict:
        return {
            "key": pix_analysis.analysis_key,
            "status": pix_analysis.status,
            "metadata": deepcopy(pix_analysis.analysis_metadata),
        }
