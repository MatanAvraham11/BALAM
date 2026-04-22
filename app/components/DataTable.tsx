type Row = Record<string, string | number>;

type Props = {
  columns: string[];
  rows: Row[];
};

export default function DataTable({ columns, rows }: Props) {
  return (
    <div className="w-full overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-700">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                className="px-4 py-2.5 text-right font-semibold border-b border-gray-200"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-6 text-center text-gray-400"
              >
                אין נתונים
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-gray-100 last:border-b-0 hover:bg-gray-50"
              >
                {columns.map((c) => (
                  <td key={c} className="px-4 py-2 text-right text-gray-800">
                    {row[c] ?? ""}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
