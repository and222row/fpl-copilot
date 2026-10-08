// Every value here ships inside the app bundle and is public by design: the
// Supabase key is the publishable (anon) key and Google client IDs are not
// secrets. No backend credential may ever be added to this file.
//
// Each variable is read with a literal `process.env.EXPO_PUBLIC_*` expression
// because Expo only inlines that exact form at build time.

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is not set. Copy mobile/.env.example to mobile/.env and fill it in.`);
  }
  return value;
}

function httpsUnlessDev(name: string, url: string): string {
  if (!__DEV__ && !url.startsWith('https://')) {
    throw new Error(`${name} must use https in release builds.`);
  }
  return url.replace(/\/+$/, '');
}

export const config = {
  apiUrl: httpsUnlessDev(
    'EXPO_PUBLIC_API_URL',
    required('EXPO_PUBLIC_API_URL', process.env.EXPO_PUBLIC_API_URL),
  ),
  supabaseUrl: httpsUnlessDev(
    'EXPO_PUBLIC_SUPABASE_URL',
    required('EXPO_PUBLIC_SUPABASE_URL', process.env.EXPO_PUBLIC_SUPABASE_URL),
  ),
  supabaseKey: required('EXPO_PUBLIC_SUPABASE_KEY', process.env.EXPO_PUBLIC_SUPABASE_KEY),
  googleWebClientId: process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? '',
  googleIosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID ?? '',
  // RevenueCat PUBLIC SDK keys (appl_... / goog_...), one per store. The secret
  // key belongs to the backend only.
  revenuecatIosKey: process.env.EXPO_PUBLIC_REVENUECAT_IOS_KEY ?? '',
  revenuecatAndroidKey: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_KEY ?? '',
  termsUrl: process.env.EXPO_PUBLIC_TERMS_URL ?? '',
  privacyUrl: process.env.EXPO_PUBLIC_PRIVACY_URL ?? '',
};
