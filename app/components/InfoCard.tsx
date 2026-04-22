type Item = { label: string; value: string };

export default function InfoCard({ items }: { items: Item[] }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-6 py-4 my-4 flex flex-wrap justify-center gap-12">
      {items.map((it) => (
        <div key={it.label} className="text-center">
          <div className="text-xs text-gray-500 mb-0.5">{it.label}</div>
          <div className="text-lg font-bold text-gray-900">{it.value}</div>
        </div>
      ))}
    </div>
  );
}
