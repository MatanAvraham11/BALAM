type Item = { label: string; value: string };

export default function InfoCard({ items }: { items: Item[] }) {
  return (
    <div className="my-4 flex flex-wrap justify-center gap-12 rounded-xl border border-gray-200 bg-white px-6 py-4 shadow-sm">
      {items.map((it) => (
        <div key={it.label} className="text-center">
          <div className="mb-0.5 text-xs font-semibold text-blue-600">
            {it.label}
          </div>
          <div className="text-lg font-bold text-gray-900">{it.value}</div>
        </div>
      ))}
    </div>
  );
}
