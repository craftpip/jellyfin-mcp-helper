// adminSlice — admin settings and API keys state and reducers
// State: adminEnv, adminEnvPending, adminKeys, adminLoading

export const adminInitialState = {
  adminEnv: null,
  adminEnvPending: [],
  adminKeys: [],
  adminLoading: false,
}

export function adminReducer(state, action) {
  switch (action.type) {
    case 'SET_ADMIN_ENV':
      return { ...state, adminEnv: action.env, adminEnvPending: action.env?.pending || [] }
    case 'SET_ADMIN_KEYS':
      return { ...state, adminKeys: action.keys || [] }
    case 'SET_ADMIN_LOADING':
      return { ...state, adminLoading: action.loading }
    default:
      return state
  }
}
