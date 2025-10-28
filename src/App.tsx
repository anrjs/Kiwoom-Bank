import { allCompanies } from "./components/companyDatabase";
import { useState, useEffect } from "react";
import { LoginPage } from "./components/LoginPage";
import { MainDashboard } from "./components/MainDashboard";
import { CompanyAnalysis } from "./components/CompanyAnalysis";
import { MyCompaniesList } from "./components/MyCompaniesList";
import { NotificationDetail } from "./components/NotificationDetail";
import { DeepAnalysisDashboard } from "./components/DeepAnalysisDashboard";
import {
  NotificationInbox,
  Notification,
} from "./components/NotificationInbox";
import { Toaster, toast } from "sonner@2.0.3";

type Screen =
  | "login"
  | "dashboard"
  | "company"
  | "mylist"
  | "notification"
  | "analysis"
  | "inbox";

export interface Company {
  name: string;
  rating: string;
  loanAmount: number;
  interestRate: number;
  delinquency: string;
  collateral: string;
  rm: string;
  ratingChange: string;
}

export default function App() {
  const [currentScreen, setCurrentScreen] =
    useState<Screen>("login");
  const [selectedCompany, setSelectedCompany] =
    useState<string>("");
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [notifications, setNotifications] = useState<
    Notification[]
  >([]);
  const [selectedNotificationId, setSelectedNotificationId] =
    useState<number | null>(null);
  const [screenHistory, setScreenHistory] = useState<Screen[]>([]);
  const [myCompanies, setMyCompanies] = useState<Company[]>([]);

  // 로그인 후 알림 시뮬레이션
  useEffect(() => {
    if (isLoggedIn && currentScreen === "dashboard") {
      // 3초 후 첫 번째 알림 (등급 하락)
      const timer1 = setTimeout(() => {
        const notification1: Notification = {
          id: 1,
          type: "down",
          companyName: "삼성전자",
          title: "신용 등급이 AA로 하향 조정되었습니다.",
          ratingChange: "AAA → AA",
          newsKeywords: "3분기 실적 악화, 반도체 시장 불확실성",
          timestamp: new Date().toLocaleString("ko-KR"),
          isRead: false,
        };
        setNotifications((prev) => [notification1, ...prev]);

        toast.error(
          "🔴 [등급 하락] 삼성전자 신용 등급이 AA로 하향 조정되었습니다.",
          {
            duration: 8000,
            action: {
              label: "상세보기",
              onClick: () => {
                setSelectedNotificationId(1);
                setNotifications((prev) =>
                  prev.map((n) =>
                    n.id === 1 ? { ...n, isRead: true } : n,
                  ),
                );
                setCurrentScreen("notification");
              },
            },
            style: {
              border: "1px solid #dc2626",
              backgroundColor: "#fee2e2",
              color: "#7f1d1d",
              cursor: "pointer",
            },
            onClick: () => {
              setSelectedNotificationId(1);
              setNotifications((prev) =>
                prev.map((n) =>
                  n.id === 1 ? { ...n, isRead: true } : n,
                ),
              );
              setCurrentScreen("notification");
            },
          },
        );
      }, 3000);

      // 8초 후 두 번째 알림 (하락 위험)
      const timer2 = setTimeout(() => {
        const notification2: Notification = {
          id: 2,
          type: "warning",
          companyName: "LG전자",
          title:
            "4분기 실적 악화로 등급 하향 가능성이 있습니다.",
          newsKeywords: "실적 부진, 가전 시장 경쟁 심화",
          timestamp: new Date().toLocaleString("ko-KR"),
          isRead: false,
        };
        setNotifications((prev) => [notification2, ...prev]);

        toast.warning(
          "🟡 [하락 위험] LG전자 4분기 실적 악화로 등급 하향 가능성이 있습니다.",
          {
            duration: 8000,
            action: {
              label: "상세보기",
              onClick: () => {
                setSelectedNotificationId(2);
                setNotifications((prev) =>
                  prev.map((n) =>
                    n.id === 2 ? { ...n, isRead: true } : n,
                  ),
                );
                setCurrentScreen("notification");
              },
            },
            style: {
              border: "1px solid #f59e0b",
              backgroundColor: "#fef3c7",
              color: "#78350f",
              cursor: "pointer",
            },
            onClick: () => {
              setSelectedNotificationId(2);
              setNotifications((prev) =>
                prev.map((n) =>
                  n.id === 2 ? { ...n, isRead: true } : n,
                ),
              );
              setCurrentScreen("notification");
            },
          },
        );
      }, 8000);

      // 13초 후 세 번째 알림 (등급 상승)
      const timer3 = setTimeout(() => {
        const notification3: Notification = {
          id: 3,
          type: "up",
          companyName: "현대자동차",
          title: "신용 등급이 AA+로 상향 조정되었습니다.",
          ratingChange: "AA → AA+",
          newsKeywords: "전기차 판매 호조, 수출 증가",
          timestamp: new Date().toLocaleString("ko-KR"),
          isRead: false,
        };
        setNotifications((prev) => [notification3, ...prev]);

        toast.success(
          "🟢 [등급 상승] 현대자동차 신용 등급이 AA+로 상향 조정되었습니다.",
          {
            duration: 8000,
            action: {
              label: "상세보기",
              onClick: () => {
                setSelectedNotificationId(3);
                setNotifications((prev) =>
                  prev.map((n) =>
                    n.id === 3 ? { ...n, isRead: true } : n,
                  ),
                );
                setCurrentScreen("notification");
              },
            },
            style: {
              border: "1px solid #16a34a",
              backgroundColor: "#dcfce7",
              color: "#14532d",
              cursor: "pointer",
            },
            onClick: () => {
              setSelectedNotificationId(3);
              setNotifications((prev) =>
                prev.map((n) =>
                  n.id === 3 ? { ...n, isRead: true } : n,
                ),
              );
              setCurrentScreen("notification");
            },
          },
        );
      }, 13000);

      return () => {
        clearTimeout(timer1);
        clearTimeout(timer2);
        clearTimeout(timer3);
      };
    }
  }, [isLoggedIn, currentScreen]);

  const handleLogin = () => {
    setIsLoggedIn(true);
    setCurrentScreen("dashboard");
  };

  const navigateToScreen = (screen: Screen) => {
    setScreenHistory((prev) => [...prev, currentScreen]);
    setCurrentScreen(screen);
  };

  const handleSearchCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    navigateToScreen("company");
  };

  const handleViewMyList = () => {
    navigateToScreen("mylist");
  };

  const handleViewNotifications = () => {
    navigateToScreen("inbox");
  };

  const handleSelectNotification = (id: number) => {
    setSelectedNotificationId(id);
    setNotifications((prev) =>
      prev.map((n) =>
        n.id === id ? { ...n, isRead: true } : n,
      ),
    );
    navigateToScreen("notification");
  };

  const handleSelectCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    navigateToScreen("company");
  };

  const handleBackToDashboard = () => {
    setScreenHistory([]);
    setCurrentScreen("dashboard");
  };

  const handleGoBack = () => {
    if (screenHistory.length > 0) {
      const previousScreen = screenHistory[screenHistory.length - 1];
      setScreenHistory((prev) => prev.slice(0, -1));
      setCurrentScreen(previousScreen);
    } else {
      setCurrentScreen("dashboard");
    }
  };

  const handleViewAnalysis = () => {
    navigateToScreen("analysis");
  };

  const handleViewNotificationDetail = () => {
    navigateToScreen("notification");
  };

  function generateRandomCompanyDetails(): Omit<Company, "name"> {
    const ratings = ["AAA", "AA+", "AA", "AA-", "A+", "A", "BBB+"];  
    const delinquencies = ["정상", "주의", "연체"];
    const collaterals = ["부동산 담보", "주식 담보", "무담보", "미정"];
    const rms = ["김민수", "이지연", "박철수", "최영희", "정수진", "강동욱"];

    return {
      rating: ratings[Math.floor(Math.random() * ratings.length)],
      loanAmount: Math.floor(Math.random() * 4000 + 1000), // 1000~5000억
      interestRate: parseFloat((Math.random() * 2 + 3).toFixed(1)), // 3.0~5.0%
      delinquency: delinquencies[Math.floor(Math.random() * delinquencies.length)],
      collateral: collaterals[Math.floor(Math.random() * collaterals.length)],
      rm: rms[Math.floor(Math.random() * rms.length)],
      ratingChange: ["유지", "상승", "하락"][Math.floor(Math.random() * 3)],
    };
  }

  const handleAddToMyCompanies = (companyName: string) => {
    const isAlreadyAdded = myCompanies.some(
      (company) => company.name === companyName
    );
    if (isAlreadyAdded) {
      toast.info(`${companyName}은(는) 이미 관심기업 목록에 있습니다.`);
      return;
    }

    const companyInfo = allCompanies.find((c) => c.name === companyName);
    if (!companyInfo) {
      toast.error(`${companyName}은(는) 등록된 기업이 아닙니다.`);
      return;
    }

    const randomDetails = generateRandomCompanyDetails();

    const newCompany: Company = {
      name: companyInfo.name,
      ...randomDetails,
    };

    setMyCompanies([...myCompanies, newCompany]);
    toast.success(`${companyName}이(가) 관심기업 목록에 추가되었습니다.`);
  };

  const unreadCount = notifications.filter(
    (n) => !n.isRead,
  ).length;

  return (
    <>
      <Toaster
        position="bottom-right"
        richColors
        closeButton
        toastOptions={{
          style: {
            cursor: "pointer",
          },
        }}
      />

      {currentScreen === "login" && (
        <LoginPage onLogin={handleLogin} />
      )}

      {currentScreen === "dashboard" && (
        <MainDashboard
          onSearchCompany={handleSearchCompany}
          onViewMyList={handleViewMyList}
          onViewNotifications={handleViewNotifications}
          unreadCount={unreadCount}
          onAddToMyCompanies={handleAddToMyCompanies}
          myCompanies={myCompanies}
        />
      )}

      {currentScreen === "company" && (
        <CompanyAnalysis
          companyName={selectedCompany}
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onViewNotificationDetail={handleViewNotificationDetail}
        />
      )}

      {currentScreen === "mylist" && (
        <MyCompaniesList
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onSelectCompany={handleSelectCompany}
          companies={myCompanies}
        />
      )}

      {currentScreen === "notification" && (
        <NotificationDetail
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onViewAnalysis={handleViewAnalysis}
        />
      )}

      {currentScreen === "analysis" && (
        <DeepAnalysisDashboard 
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
        />
      )}

      {currentScreen === "inbox" && (
        <NotificationInbox
          notifications={notifications}
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onSelectNotification={handleSelectNotification}
        />
      )}
    </>
  );
}