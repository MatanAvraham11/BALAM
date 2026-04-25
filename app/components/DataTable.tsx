type Row = Record<string, string | number>;

type Props = {
  columns: string[];
  rows: Row[];
};

export default function DataTable({ columns, rows }: Props) {
  return (
    <div className="w-full overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-blue-50 text-gray-700">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                className="border-b border-gray-200 px-4 py-3 text-right text-xs font-bold uppercase tracking-wide"
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
                className="px-4 py-8 text-center text-gray-400"
              >
                אין נתונים
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-gray-100 transition-colors last:border-b-0 hover:bg-gray-50"
              >
                {columns.map((c) => {
                  const isMonospace = c === "מספר בלון" || c === "מידה / הערה";

                  return (
                    <td
                      key={c}
                      className={`px-4 py-3 text-right text-gray-800 ${
                        isMonospace ? "font-mono tabular-nums" : ""
                      }`}
                    >
                      {row[c] ?? ""}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
