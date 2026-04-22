# Python Standards Refactoring Plan for Toto Project

## Executive Summary

This document outlines a comprehensive plan to refactor the Toto cycling fantasy application to follow modern Python development standards. The goal is to improve maintainability, testability, and scalability while preserving all existing functionality.

## Current Codebase Analysis

### Strengths
- **Modular database layer**: `src/db.py` is well-separated
- **Voice processing**: `src/voice.py` has good separation of concerns  
- **Effective caching**: Good use of `@st.cache_data`
- **Clean internationalization**: Well-structured translation system

### Issues to Address

1. **Monolithic Structure**: `participant.py` is 500+ lines with mixed concerns (UI, business logic, database)
2. **Limited OOP**: Mostly procedural code with minimal object-oriented design
3. **Tight Coupling**: UI, business logic, and database layers are intertwined
4. **Inconsistent Error Handling**: Some areas have try/catch, others don't
5. **Minimal Type Hints**: Limited use of Python's type system
6. **Global State**: Heavy reliance on Streamlit session state

## Proposed Architecture

```
toto/
├── src/
│   ├── core/                  # Core domain logic
│   │   ├── models/            # Data models and business logic
│   │   ├── services/          # Service layer
│   │   ├── repositories/      # Data access interfaces
│   │   └── exceptions/       # Custom exceptions
│   ├── infrastructure/        # External integrations
│   │   ├── database/          # Database implementations
│   │   ├── llm/               # LLM integration
│   │   └── storage/           # File storage, caching
│   ├── presentation/          # UI layer
│   │   ├── streamlit/         # Streamlit-specific UI
│   │   └── components/        # Reusable UI components
│   └── shared/                # Cross-cutting concerns
│       ├── utils/             # Utility functions
│       ├── i18n/              # Internationalization
│       └── config/            # Configuration management
├── tests/                     # Comprehensive test suite
├── scripts/                   # CLI scripts and utilities
└── docs/                      # Documentation
```

## Key Components

### 1. Domain Models (`src/core/models/`)

```python
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

@dataclass
class Rider:
    url: str
    name: str
    nickname: Optional[str] = None
    nationality: Optional[str] = None
    team_name: Optional[str] = None

@dataclass
class Race:
    name: str
    deadline: Optional[datetime] = None
    stages: List['Stage'] = field(default_factory=list)

@dataclass  
class FantasyTeam:
    account_id: str
    race_name: str
    team_name: str
    rider_urls: List[str]
    created_at: datetime = field(default_factory=datetime.now)
```

### 2. Service Layer (`src/core/services/`)

```python
from typing import List, Optional
from src.core.models import Rider, FantasyTeam
from src.core.repositories import RiderRepository, TeamRepository

class RiderService:
    def __init__(self, rider_repo: RiderRepository):
        self.rider_repo = rider_repo

    def search_riders(self, query: str, race_name: Optional[str] = None) -> List[Rider]:
        """Search riders with optional race filtering"""
        if race_name:
            return self.rider_repo.find_by_race(race_name, query)
        return self.rider_repo.find_all(query)

    def get_rider_by_url(self, rider_url: str) -> Optional[Rider]:
        return self.rider_repo.find_by_url(rider_url)

class TeamService:
    def __init__(self, team_repo: TeamRepository, rider_service: RiderService):
        self.team_repo = team_repo
        self.rider_service = rider_service

    def create_team(self, team_data: FantasyTeam) -> FantasyTeam:
        self._validate_team(team_data)
        return self.team_repo.create(team_data)

    def _validate_team(self, team_data: FantasyTeam):
        if len(team_data.rider_urls) > 15:
            raise ValueError("Team cannot have more than 15 riders")
        
        if len(set(team_data.rider_urls)) != len(team_data.rider_urls):
            raise ValueError("Duplicate riders not allowed")
        
        for rider_url in team_data.rider_urls:
            if not self.rider_service.get_rider_by_url(rider_url):
                raise ValueError(f"Rider {rider_url} not found")
```

### 3. Repository Layer (`src/core/repositories/`)

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from src.core.models import Rider, FantasyTeam

class RiderRepository(ABC):
    @abstractmethod
    def find_all(self, query: Optional[str] = None) -> List[Rider]:
        pass

    @abstractmethod
    def find_by_race(self, race_name: str, query: Optional[str] = None) -> List[Rider]:
        pass

    @abstractmethod
    def find_by_url(self, rider_url: str) -> Optional[Rider]:
        pass

class TeamRepository(ABC):
    @abstractmethod
    def create(self, team: FantasyTeam) -> FantasyTeam:
        pass

    @abstractmethod
    def find_by_account(self, account_id: str, race_name: str) -> Optional[FantasyTeam]:
        pass

    @abstractmethod
    def update(self, team: FantasyTeam) -> FantasyTeam:
        pass
```

### 4. Infrastructure Layer (`src/infrastructure/`)

```python
# src/infrastructure/database/duckdb_repository.py
from src.core.repositories import RiderRepository
from src.core.models import Rider
from src.infrastructure.database.connection import get_connection

class DuckDBRiderRepository(RiderRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def find_all(self, query: Optional[str] = None) -> List[Rider]:
        conn = get_connection(self.db_path)
        try:
            if query:
                # Implement search logic
                sql = """
                    SELECT rider_url, name, nickname, nationality, team_name
                    FROM riders
                    WHERE name IS NOT NULL AND LOWER(name) LIKE LOWER(?)
                    ORDER BY name
                """
                rows = conn.execute(sql, [f"%{query}%"]).fetchall()
            else:
                rows = conn.execute("""
                    SELECT rider_url, name, nickname, nationality, team_name
                    FROM riders
                    WHERE name IS NOT NULL
                    ORDER BY name
                """).fetchall()
            return [self._map_to_rider(row) for row in rows]
        finally:
            conn.close()

    def _map_to_rider(self, row) -> Rider:
        return Rider(
            url=row[0],
            name=row[1],
            nickname=row[2],
            nationality=row[3],
            team_name=row[4]
        )
```

### 5. Streamlit UI Refactoring

```python
# src/presentation/streamlit/participant_app.py
import streamlit as st
from src.core.services import RiderService, TeamService
from src.shared.i18n import Translator

class ParticipantApp:
    def __init__(self, db_path: str):
        # Initialize services
        rider_repo = DuckDBRiderRepository(db_path)
        team_repo = DuckDBTeamRepository(db_path)
        self.rider_service = RiderService(rider_repo)
        self.team_service = TeamService(team_repo, self.rider_service)
        self.translator = Translator()

        # Initialize UI state
        self._initialize_state()

    def _initialize_state(self):
        if "account" not in st.session_state:
            st.session_state.account = None
        if "selected_riders" not in st.session_state:
            st.session_state.selected_riders = []

    def run(self):
        self._show_header()
        self._handle_authentication()

        if st.session_state.account:
            self._show_race_selection()
            self._show_team_management()

    def _show_rider_search(self):
        search_query = st.text_input(
            f"🔍 {self.translator.t('participant_search_rider')}",
            key="rider_search"
        )

        if search_query:
            try:
                riders = self.rider_service.search_riders(
                    search_query,
                    st.session_state.selected_race
                )
                self._display_search_results(riders)
            except Exception as e:
                st.error(f"Search error: {e}")
```

## Key Improvements Over Current Implementation

### 1. Separation of Concerns
- **UI Layer**: Only handles presentation and user interaction
- **Service Layer**: Contains all business logic and rules
- **Repository Layer**: Handles data access and persistence
- **Domain Models**: Pure data structures with no behavior

### 2. Type Safety
- Comprehensive type hints throughout all layers
- Data classes for domain models with proper validation
- Abstract base classes for repository interfaces
- Runtime type checking where appropriate

### 3. Testability
- Dependency injection makes components easily testable
- Clear interfaces allow for mocking in tests
- Business logic completely separated from UI
- Repository pattern enables isolated testing

### 4. Maintainability
- Modular structure with clear boundaries
- Consistent naming conventions
- Proper error handling and logging
- Comprehensive documentation

### 5. Scalability
- Easy to add new features without breaking existing code
- Can swap implementations (e.g., different databases)
- Clear extension points for new functionality
- Supports team growth and parallel development

## Migration Plan

### Phase 1: Foundation (2-3 weeks)
- [ ] Create core domain models (`Rider`, `Team`, `Race`, etc.)
- [ ] Implement repository interfaces and basic implementations
- [ ] Build service layer with core business logic
- [ ] Set up dependency injection framework
- [ ] Implement configuration management

### Phase 2: Infrastructure (1-2 weeks)
- [ ] Refactor database layer to use repositories
- [ ] Implement LLM integration as a service
- [ ] Set up proper logging and monitoring
- [ ] Add comprehensive error handling
- [ ] Implement caching strategy

### Phase 3: UI Refactoring (3-4 weeks)
- [ ] Create base UI component structure
- [ ] Migrate authentication flow
- [ ] Refactor race selection interface
- [ ] Implement team management components
- [ ] Create reusable UI components
- [ ] Add client-side validation

### Phase 4: Testing & Quality (2 weeks)
- [ ] Implement unit tests for core services
- [ ] Add integration tests for key flows
- [ ] Set up CI/CD pipeline
- [ ] Add end-to-end testing
- [ ] Performance optimization
- [ ] Security review

### Phase 5: Deployment (1 week)
- [ ] Gradual rollout with feature flags
- [ ] Monitoring and error tracking setup
- [ ] User feedback collection
- [ ] Bug fixing and polish
- [ ] Documentation finalization

## Python Standards Implementation

### Type Hints and Data Validation

```python
from typing import List, Optional, Dict, Tuple, Protocol, runtime_checkable
from pydantic import BaseModel, Field, validator

@runtime_checkable
class Searchable(Protocol):
    def search(self, query: str) -> List[Dict[str, str]]: ...

class RiderCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    nationality: Optional[str] = Field(None, max_length=2)
    team_name: Optional[str] = Field(None, max_length=50)
    
    @validator('name')
    def validate_name(cls, v):
        if not v.replace(' ', '').isalpha():
            raise ValueError('Name must contain only letters and spaces')
        return v.title()
```

### Error Handling

```python
class RiderNotFoundError(Exception):
    """Raised when a rider is not found in the database"""
    def __init__(self, rider_name: str):
        self.rider_name = rider_name
        super().__init__(f"Rider '{rider_name}' not found")

class TeamValidationError(Exception):
    """Raised when team composition is invalid"""
    def __init__(self, message: str, details: Optional[Dict] = None):
        self.details = details
        super().__init__(message)

# Usage in service layer
try:
    rider = rider_service.get_rider(rider_url)
except RiderNotFoundError as e:
    logger.warning(f"Rider not found: {e.rider_name}")
    raise UserFriendlyError("Rider not found in database") from e
```

### Configuration Management

```python
from pydantic import BaseSettings, Field

class AppSettings(BaseSettings):
    database_url: str = Field(..., env="DATABASE_URL")
    llm_api_key: str = Field(..., env="MISTRAL_API_KEY")
    cache_ttl: int = 300
    max_team_size: int = 15
    debug_mode: bool = False
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

# Usage
settings = AppSettings()
```

### Logging

```python
import logging
from pythonjsonlogger import jsonlogger

def setup_logging():
    logger = logging.getLogger("toto")
    logger.setLevel(logging.INFO)

    # JSON formatting for better log analysis
    log_handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s '
        '%(filename)s:%(lineno)d'
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # Add file handler for production
    if not settings.debug_mode:
        file_handler = logging.FileHandler('app.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
```

## Testing Strategy

### Unit Testing Example

```python
import pytest
from unittest.mock import Mock, patch
from src.core.services import RiderService
from src.core.models import Rider

def test_rider_service_search():
    # Setup
    mock_repo = Mock()
    mock_repo.find_all.return_value = [
        Rider(url="rider1", name="Test Rider", nationality="NL")
    ]

    service = RiderService(mock_repo)

    # Test
    results = service.search_riders("Test")

    # Assert
    assert len(results) == 1
    assert results[0].name == "Test Rider"
    mock_repo.find_all.assert_called_once_with("Test")

def test_rider_service_search_empty():
    mock_repo = Mock()
    mock_repo.find_all.return_value = []
    
    service = RiderService(mock_repo)
    results = service.search_riders("Nonexistent")
    
    assert len(results) == 0
```

### Integration Testing

```python
@pytest.mark.integration
class TestRiderServiceIntegration:
    @pytest.fixture
    def service(self):
        # Use real repository with test database
        repo = DuckDBRiderRepository(":memory:")
        # Seed test data
        return RiderService(repo)

    def test_search_and_retrieve(self, service):
        # Test full flow from search to retrieval
        results = service.search_riders("Test")
        assert len(results) > 0
        
        rider = service.get_rider_by_url(results[0].url)
        assert rider is not None
        assert rider.name == results[0].name
```

## Benefits of This Refactoring

### For Developers
- ✅ **Easier Maintenance**: Clear separation of concerns
- ✅ **Better Testability**: Components can be tested in isolation
- ✅ **Improved Collaboration**: Multiple developers can work on different layers
- ✅ **Faster Onboarding**: Clear structure helps new team members
- ✅ **Better Tooling**: IDE support with type hints and autocompletion

### For the Application
- ✅ **Improved Performance**: Optimized database queries
- ✅ **Better Error Handling**: Graceful degradation
- ✅ **Enhanced Security**: Proper input validation
- ✅ **Scalability**: Can handle more users and data
- ✅ **Extensibility**: Easy to add new features

### For Users
- ✅ **More Reliable**: Fewer bugs and edge cases
- ✅ **Better Error Messages**: Clear, actionable feedback
- ✅ **Improved Performance**: Faster response times
- ✅ **Consistent Behavior**: Predictable application behavior

## Implementation Recommendations

1. **Start with Core Domain**: Begin refactoring with the domain models and services
2. **Use Feature Flags**: Deploy changes gradually to minimize risk
3. **Maintain Backward Compatibility**: Ensure existing functionality continues to work
4. **Prioritize Testing**: Build tests alongside new components
5. **Document Decisions**: Keep an architecture decision record
6. **Iterative Approach**: Refactor in small, manageable chunks
7. **Code Reviews**: Maintain quality through peer reviews
8. **Monitor Performance**: Ensure refactoring doesn't degrade performance

## Conclusion

This refactoring plan transforms the current procedural/monolithic codebase into a modern, maintainable Python application following current best practices. The proposed architecture provides:

- **Clean separation of concerns** through layered architecture
- **Type safety** with comprehensive type hints
- **Testability** through dependency injection and interfaces
- **Maintainability** with modular structure and clear boundaries
- **Scalability** for future growth and features

The migration can be done gradually to minimize disruption, with each phase delivering tangible improvements. The result will be a codebase that's easier to maintain, extend, and test while providing the same (or better) functionality to users.