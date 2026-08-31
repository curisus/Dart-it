from dart_crawler.query_limits import QueryPolicy
from tests.excel_service_recorder import RecordingExcelQueryService
from tests.excel_service_responses import ExcelServiceResponses


class RecordingExcelServiceFactory:
    def __init__(self, responses: ExcelServiceResponses) -> None:
        self.responses = responses
        self.policies: list[QueryPolicy] = []
        self.services: list[RecordingExcelQueryService] = []

    def create(self, policy: QueryPolicy) -> RecordingExcelQueryService:
        self.policies.append(policy)
        service = RecordingExcelQueryService(self.responses)
        self.services.append(service)
        return service
