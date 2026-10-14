from abc import ABC, abstractmethod
from app.data.demo import get_case
class AIExtractionService(ABC):
 @abstractmethod
 def extract_facts(self): ...
 @abstractmethod
 def find_evidence(self): ...
 @abstractmethod
 def detect_conflicts(self): ...
 @abstractmethod
 def summarize_case(self): ...
class MockAIExtractionService(AIExtractionService):
 def extract_facts(self): return [{"name":"physiotherapy_duration","value":8,"unit":"weeks","confidence":.98}]
 def find_evidence(self): return get_case()["evidence"]
 def detect_conflicts(self): return [x for x in get_case()["findings"] if x["status"]=="conflict"]
 def summarize_case(self): return get_case()
