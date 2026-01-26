import { Flame, Building2, Shield } from 'lucide-react';
import type { ScoreResponse } from '../types';

interface ScorePanelProps {
  score: ScoreResponse | null;
  isLoading: boolean;
}

const POI_ICONS: Record<string, React.ReactNode> = {
  fire: <Flame className="w-5 h-5 text-orange-500" />,
  hospital: <Building2 className="w-5 h-5 text-red-500" />,
  police: <Shield className="w-5 h-5 text-blue-500" />,
};

const POI_LABELS: Record<string, string> = {
  fire: 'Brannstasjon',
  hospital: 'Sykehus',
  police: 'Politistasjon',
};

function getScoreColor(score: number): string {
  if (score >= 70) return 'text-green-600';
  if (score >= 40) return 'text-yellow-600';
  return 'text-red-600';
}

function formatDistance(meters: number): string {
  if (meters < 0) return 'Ikke funnet';
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(1)} km`;
}

export function ScorePanel({ score, isLoading }: ScorePanelProps) {
  if (isLoading) {
    return (
      <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 w-72 z-[1000]">
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
          <div className="h-8 bg-gray-200 rounded w-1/2 mb-4"></div>
          <div className="space-y-2">
            <div className="h-4 bg-gray-200 rounded"></div>
            <div className="h-4 bg-gray-200 rounded"></div>
            <div className="h-4 bg-gray-200 rounded"></div>
          </div>
        </div>
      </div>
    );
  }

  if (!score) {
    return (
      <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 w-72 z-[1000]">
        <h3 className="font-semibold text-gray-700 mb-2">Sikkerhetsscore</h3>
        <p className="text-gray-500 text-sm">
          Klikk på kartet for å se sikkerhetsscoren for et punkt.
        </p>
      </div>
    );
  }

  return (
    <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 w-80 z-[1000]">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="font-semibold text-gray-700">Sikkerhetsscore</h3>
          <p className="text-xs text-gray-400">
            {score.lat.toFixed(4)}, {score.lng.toFixed(4)}
          </p>
        </div>
        <div className={`text-3xl font-bold ${getScoreColor(score.score)}`}>
          {score.score.toFixed(0)}
        </div>
      </div>

      <div className="space-y-3">
        {score.components.map((comp) => (
          <div key={comp.poi_type} className="border-t pt-2">
            <div className="flex items-center gap-2 mb-1">
              {POI_ICONS[comp.poi_type]}
              <span className="font-medium text-sm">
                {POI_LABELS[comp.poi_type] || comp.poi_type}
              </span>
              <span className="ml-auto text-xs text-gray-500">
                vekt: {(comp.weight * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-600">
                {comp.nearest_name || 'Ukjent'}
              </span>
              <span className="text-gray-500">
                {formatDistance(comp.distance_m)}
              </span>
            </div>
            <div className="mt-1 h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full ${
                  comp.subscore >= 70
                    ? 'bg-green-500'
                    : comp.subscore >= 40
                    ? 'bg-yellow-500'
                    : 'bg-red-500'
                }`}
                style={{ width: `${comp.subscore}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-2 border-t text-xs text-gray-400">
        Modell: {score.model_version}
      </div>
    </div>
  );
}
