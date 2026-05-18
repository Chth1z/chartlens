// Barrel re-export. Implementation lives in ./api/* modules grouped by API surface.
export type {
  ReviewBand,
  EvidencePack,
  FieldResult,
  OcrBlock,
  OcrQuality,
  ProcessingRun,
  DocumentFragment,
  ModelCallLog,
  VisionFallbackRecord,
  CaseDiagnostics,
  CaseRecord,
  CaseSummary,
  DocumentIrResponse,
  SourceOcrResponse,
} from "./api/cases";
export type {
  FieldDefinition,
  FieldDictionary,
  FieldGroupDefinition,
  EvidenceDisplayConfig,
  ProjectConfig,
} from "./api/fields";
export type { AuthStatus } from "./api/auth";
export type {
  ModelProfile,
  ModelProfilesResponse,
  ModelProfileSelectionResponse,
  ProviderModel,
  ModelProviderSelection,
  ModelProvider,
  ModelProvidersResponse,
  ModelProviderUpdatePayload,
  ModelProviderUpdateResponse,
  ModelProviderFetchResponse,
  ModelProviderActivationResponse,
} from "./api/models";
export type {
  SystemSettingsResponse,
  FieldDictionarySettingsResponse,
  RuntimeSettingsResponse,
  RuntimeServices,
  RuntimeServiceStatus,
  RuntimeServiceCheck,
  RuntimeServiceAction,
  SettingsValidationPayload,
  SettingsValidationResponse,
  MaintenanceResult,
} from "./api/system";
