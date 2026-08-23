// scanSlice — scan-related state and reducers
// State: scanId, scanRunning, scanProgress

export const scanInitialState = {
  scanId: null,
  scanRunning: false,
  scanProgress: null,
}

export function scanReducer(state, action) {
  switch (action.type) {
    case 'SET_SCAN_ID':
      return { ...state, scanId: action.scanId }
    case 'SET_SCAN_RUNNING':
      return { ...state, scanRunning: action.scanRunning }
    case 'SET_SCAN_PROGRESS':
      return { ...state, scanProgress: action.progress }
    default:
      return state
  }
}
