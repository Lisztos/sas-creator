from sas_creator.config import AppConfig
from sas_creator.steps.base import Step
from sas_creator.steps.login import LoginStep
from sas_creator.steps.select_tramite import SelectTramiteStep


def get_step_pipeline(config: AppConfig) -> list[Step]:
    """Return the ordered list of steps to execute.

    Add new steps here as they are implemented.
    """
    return [
        LoginStep(config),
        SelectTramiteStep(config),
        # Future steps:
        # FillCompanyDataStep(config),
        # UploadDocumentsStep(config),
        # ReviewAndSubmitStep(config),
    ]
