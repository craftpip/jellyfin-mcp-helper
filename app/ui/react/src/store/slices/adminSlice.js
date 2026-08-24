// adminSlice — admin settings state

export const adminInitialState = {
  adminEnv: null,
  adminEnvPending: [],
  adminLoading: false,
}

export function adminReducer(state, action) {
  switch (action.type) {
    case 'SET_ADMIN_ENV':
      return { ...state, adminEnv: action.env, adminEnvPending: action.env?.pending || [] }
    case 'SET_ADMIN_LOADING':
      return { ...state, adminLoading: action.loading }
    default:
      return state
  }
}
