import Tabs from "./components/Tabs";
import BalamTab from "./components/BalamTab";
import DrawingTab from "./components/DrawingTab";

export default function Home() {
  return (
    <div className="flex flex-col items-center min-h-screen">
      <header className="w-full max-w-2xl mx-auto pt-10 pb-3 text-center">
        <h1 className="text-4xl font-extrabold text-primary tracking-tight">
          נתיב | Nativ
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          חילוץ נתונים חכם ממסמכי רכש ושרטוטים הנדסיים
        </p>
      </header>

      <hr className="w-full max-w-2xl border-t border-gray-200 mb-6" />

      <main className="w-full max-w-2xl mx-auto px-4 pb-16">
        <Tabs
          tabs={[
            { id: "balam", label: 'בל"מ', content: <BalamTab /> },
            { id: "drawing", label: "שרטוט", content: <DrawingTab /> },
          ]}
        />
      </main>
    </div>
  );
}
