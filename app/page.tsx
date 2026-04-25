import Tabs from "./components/Tabs";
import BalamTab from "./components/BalamTab";
import DrawingTab from "./components/DrawingTab";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center bg-gray-50">
      <header className="mx-auto w-full max-w-4xl px-4 pt-10 pb-4 text-center">
        <h1 className="text-4xl font-extrabold tracking-tight text-blue-600">
          נתיב | Nativ
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          חילוץ נתונים חכם ממסמכי רכש ושרטוטים הנדסיים
        </p>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 pb-16">
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
