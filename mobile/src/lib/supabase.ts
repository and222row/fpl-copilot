import { createClient } from '@supabase/supabase-js';
import { AppState, Platform } from 'react-native';

import { config } from '@/lib/config';
import { encryptedStorage } from '@/lib/encrypted-storage';

export const supabase = createClient(config.supabaseUrl, config.supabaseKey, {
  auth: {
    storage: encryptedStorage,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false,
  },
});

// Refresh tokens only while the app is in the foreground; a background timer
// would be killed by the OS anyway and wake the radio for nothing.
if (Platform.OS !== 'web') {
  AppState.addEventListener('change', (state) => {
    if (state === 'active') supabase.auth.startAutoRefresh();
    else supabase.auth.stopAutoRefresh();
  });
}
