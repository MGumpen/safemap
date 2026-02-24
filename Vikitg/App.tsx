/*
import { useState } from 'react';
import { MapView } from '../frontend/src/components/MapView';
import { ScorePanel } from '../frontend/src/components/ScorePanel';
import { Legend } from './components/Legend';
import type { ScoreResponse } from '../frontend/src/types';

function App() {
  const [currentScore, setCurrentScore] = useState<ScoreResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleScoreChange = (score: ScoreResponse | null, loading: boolean) => {
    setCurrentScore(score);
    setIsLoading(loading);
  };

  return (
    <div className="h-screen w-screen flex flex-col">
      <header className="bg-slate-800 text-white px-4 py-3 flex items-center justify-between z-10">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">SafeMap</h1>
          <span className="text-slate-400 text-sm">Sikkerhetskart for Norge</span>
        </div>
        <div className="text-sm text-slate-400">
          Totalforsvarsåret 2026
        </div>
      </header>

      <main className="flex-1 relative">
        <MapView onScoreChange={handleScoreChange} />
        <ScorePanel score={currentScore} isLoading={isLoading} />
        <Legend className="absolute bottom-4 left-4 z-[1000]" />
      </main>
    </div>
  );
}

export default App;
*/
