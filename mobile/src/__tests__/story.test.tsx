import { render, screen, userEvent } from '@testing-library/react-native';

const mockPush = jest.fn();
const mockStory = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-image', () => ({ Image: () => null }));
jest.mock('expo-router', () => ({
  router: { push: (...a: unknown[]) => mockPush(...a) },
  useLocalSearchParams: () => ({ id: '10', alert: '7' }),
}));
jest.mock('@/lib/api', () => ({ ApiError: class ApiError extends Error {} }));
jest.mock('@/lib/query', () => ({
  useTeamId: () => 1234,
  useStory: (...a: unknown[]) => mockStory(...a),
}));

import { NewsCard } from '@/components/news-card';
import StoryScreen from '@/app/story/[id]';
import type { SquadIssue, Story } from '@/lib/api';
import { initials, warningHeadline, warningSummary } from '@/lib/news';

const ok = (data: unknown) => ({ data, isPending: false, isError: false, isRefetching: false, refetch: jest.fn() });

const STORY: Story = {
  player: {
    id: 10, name: 'João Pedro', full_name: 'João Pedro Junqueira', team: 'CHE', team_name: 'Chelsea', position: 'FWD',
    price: 7.8, photo: 'https://x/250x250/p1.png', kit: null, status: 'i', status_label: 'Injured',
    news: 'Thigh injury - Unknown return date', chance: 0,
  },
  headline: 'João Pedro ruled out',
  summary: 'Thigh injury - Unknown return date',
  severity: 'critical',
  published_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  history: [
    { at: new Date(Date.now() - 2 * 86_400_000).toISOString(), event_type: 'ruled_out', news: 'Thigh injury - Unknown return date', status: 'Injured', chance: 0 },
    { at: new Date(Date.now() - 4 * 86_400_000).toISOString(), event_type: 'status_change', news: 'Knock - 75% chance of playing', status: 'Doubtful', chance: 0.75 },
  ],
  you: { owned: true, starting: true, captain: false, projected_next: 0, gameweek: 'Gameweek 9', plan: { out: 'João Pedro', in: 'Isak', in_player_id: 379 } },
  replacements: [{ player_id: 379, name: 'Isak', team: 'LIV', price: 9.1, photo: null, kit: null, xpts_horizon: 25.6 }],
  horizon: 5,
  fixtures: [{ gameweek: 9, opponents: ['MUN (H)'] }, { gameweek: 10, opponents: ['SUN (A)'] }],
};

beforeEach(() => {
  mockPush.mockReset();
  mockStory.mockReset();
});

test('the article: headline, what it means for you, history, replacements, fixtures', async () => {
  const user = userEvent.setup();
  mockStory.mockReturnValue(ok(STORY));
  await render(<StoryScreen />);
  expect(mockStory).toHaveBeenCalledWith(1234, 10, 7);
  expect(screen.getByTestId('story-headline').props.children).toBe('João Pedro ruled out');
  expect(screen.getByText('Chelsea · FWD · £7.8m · 2 days ago')).toBeTruthy();
  expect(screen.getByText("He's in your starting XI.")).toBeTruthy();
  expect(screen.getByText("He's projected 0.0 points in Gameweek 9.")).toBeTruthy();
  expect(screen.getByText('João Pedro → Isak')).toBeTruthy();
  expect(screen.getByText('Knock - 75% chance of playing')).toBeTruthy();
  expect(screen.getByText('Replacements you can afford')).toBeTruthy();
  expect(screen.getByText('MUN (H)')).toBeTruthy();

  await user.press(screen.getByTestId('replacement-379'));
  expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/player/[id]', params: { id: '379' } });
  await user.press(screen.getByText('Plan transfers'));
  expect(mockPush).toHaveBeenLastCalledWith('/transfers');
});

test('a news card reads like a headline and opens on tap', async () => {
  const user = userEvent.setup();
  const opened = jest.fn();
  await render(
    <NewsCard photo={null} initials="JP" tone="danger" label="Unavailable" title="João Pedro is injured"
      summary="Thigh injury - Unknown return date" meta="CHE · FWD · in your squad" onPress={opened} testID="card" />,
  );
  expect(screen.getByText('JP')).toBeTruthy(); // no photo: initials
  expect(screen.getByText('Read more ›')).toBeTruthy();
  await user.press(screen.getByTestId('card'));
  expect(opened).toHaveBeenCalled();
});

test('squad warning wording', () => {
  const issue = (extra: Partial<SquadIssue>): SquadIssue => ({
    player_id: 1, name: 'Thomas', team: 'BHA', position: 'DEF', price: 4.5, xpts: 2, p_start: 0.4, status: 'a',
    news: '', chance_of_playing: null, reason: 'Rotation risk', ...extra,
  } as SquadIssue);
  expect(warningHeadline(issue({ status: 'i' }))).toBe('Thomas is injured');
  expect(warningHeadline(issue({ status: 'd' }))).toBe('Thomas is a doubt');
  expect(warningHeadline(issue({}))).toBe('Thomas may not start');
  expect(warningSummary(issue({}))).toBe('Projected to start 40% of the time.');
  expect(warningSummary(issue({ news: 'Knock - 75% chance of playing' }))).toBe('Knock - 75% chance of playing');
  expect(initials('João Pedro')).toBe('JP');
  expect(initials('Haaland')).toBe('HA');
  expect(initials('B.Fernandes')).toBe('BF');
});
