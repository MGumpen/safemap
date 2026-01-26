/* interface LegendProps {
  className?: string;
}

export function Legend({ className = '' }: LegendProps) {
  return (
    <div className={`bg-white rounded-lg shadow-lg p-3 ${className}`}>
      <h4 className="text-sm font-semibold text-gray-700 mb-2">Sikkerhetsscore</h4>
      <div className="flex items-center gap-2">
        <div
          className="h-4 w-32 rounded"
          style={{
            background: 'linear-gradient(to right, #ef4444, #f59e0b, #22c55e)',
          }}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-500 mt-1">
        <span>0 (Lav)</span>
        <span>50</span>
        <span>100 (Høy)</span>
      </div>
    </div>
  );
}
*/