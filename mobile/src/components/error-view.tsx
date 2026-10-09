import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { ThemedText } from '@/components/themed-text';
import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { ApiError } from '@/lib/api';

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const theme = useTheme();
  return (
    <View style={[styles.box, { backgroundColor: theme.dangerSoft }]} accessibilityRole="alert" testID="error-view">
      <ThemedText type="small" themeColor="danger">
        {errorMessage(error)}
      </ThemedText>
      {onRetry ? <Button title="Try again" variant="secondary" compact onPress={onRetry} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 10, borderRadius: Radius.md, padding: 14 },
});
