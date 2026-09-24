/** Generated from app/models/schemas.py + openapi.json — Phase 1.3 typed contracts.
 *  Hand-written for now; future: `npx openapi-typescript openapi.json` or `datamodel-codegen`.
 *  Keep in sync with `app/models/schemas.py` (single source of truth).
 */

export type OperationMode = "organize" | "normalize"
export type ItemKind = "movie" | "series" | "skip" | "extra"
export type ScanStatus = "running" | "completed" | "confirmed" | "failed" | "cancelled"
export type ConfirmStatus = "idle" | "running" | "completed" | "failed"
export type ConfirmPhase =
  | "idle"
  | "preparing"
  | "moving"
  | "deleting_source"
  | "triggering_jellyfin"
  | "completed"
  | "failed"

export interface ScanRequest {
  replaceExisting?: boolean
  operation?: OperationMode
}

export interface CandidateTarget {
  path: string
  label: string
  evidence: string
  source?: string
  reclassify_as_movie?: boolean
}

export interface ScannedItem {
  confirmId: string
  sourcePath: string
  name: string
  item_type: ItemKind
  confidence: number
  reason: string
  targetPath: string
  action: "move" | "replace" | "skip"
  error?: string | null
  confirmed: boolean
  showFolderExists: boolean
  seasonFolderExists: boolean
  fileExists: boolean
  fileSize?: number | null
  crossDrive: boolean
  suspect: boolean
  flags: string[]
  corrected: boolean
  correction_note?: string | null
  candidateTargets: CandidateTarget[]
  locked?: boolean
}

export interface ScanCounts {
  total: number
  movies: number
  series: number
  skipped: number
  moved: number
  replaced: number
  failed: number
}

export interface ScanPlan {
  scan_id: string
  status: ScanStatus
  operation: OperationMode
  items: ScannedItem[]
  counts: ScanCounts
  skipped_in_progress: number
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  total_candidates: number
  processed_candidates: number
  current_candidate?: string | null
  current_candidate_index: number
  confirmed_at?: string | null
  error?: string | null
  service_errors: Record<string, string>
  confirm_status: ConfirmStatus
  confirm_phase: ConfirmPhase
  confirm_current_item?: string | null
  confirm_current_target?: string | null
  confirm_started_at?: string | null
  confirm_total: number
  confirm_processed: number
  confirm_start_moved: number
  confirm_start_replaced: number
  confirm_start_failed: number
  confirm_current_size_bytes?: number | null
  confirm_current_copied_bytes?: number | null
  confirm_current_speed_bytes?: number | null
  confirm_current_percent?: number | null
  confirm_cross_drive?: boolean | null
  confirm_note?: string | null
  confirm_last_update_at?: string | null
  confirm_queue_length: number
  confirm_queue_items: number
}

export interface ScanProgress {
  scan_id?: string | null
  status: ScanStatus | ConfirmStatus | string
  processed: number
  total: number
  percent: number
  current_file?: string | null
  lines?: string[]
  summary?: Record<string, unknown>
}

export interface ConfirmProgress {
  status: ConfirmStatus | string
  processed: number
  total: number
  counts: Partial<ScanCounts>
  queue_length?: number
  queue_items?: number
}

export interface ScanReport {
  scan_id?: string
  summary: ScanCounts & { scan_id?: string; operation?: string }
  items: ScannedItem[]
  report_md?: string
  service_errors?: Record<string, string> | null
  progress?: ScanProgress | null
  hint?: string
}

// Typed apiCall helpers — mirrors apiClient.js:22 but with generics
export type ApiMethod = "GET" | "POST" | "PATCH" | "DELETE"
