import { Image } from 'expo-image';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';

// Roughly one player in eight has no headshot and the URL returns 403, so a
// failed load falls back to the position.
export function PlayerPhoto({ uri, position, size = 56 }: { uri: string | null; position: string; size?: number }) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size * 1.27, borderRadius: 8, backgroundColor: theme.backgroundSelected };

  if (!uri || failed) {
    return (
      <View style={[box, styles.center]}>
        <ThemedText type="smallBold" themeColor="textSecondary">
          {position}
        </ThemedText>
      </View>
    );
  }
  return (
    <Image
      source={{ uri }}
      style={box}
      contentFit="cover"
      cachePolicy="memory-disk"
      onError={() => setFailed(true)}
      accessibilityIgnoresInvertColors
    />
  );
}

const styles = StyleSheet.create({ center: { alignItems: 'center', justifyContent: 'center' } });
