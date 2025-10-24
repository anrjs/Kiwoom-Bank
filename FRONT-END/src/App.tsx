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

  const handleSearchCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    setCurrentScreen("company");
  };

  const handleViewMyList = () => {
    setCurrentScreen("mylist");
  };

  const handleViewNotifications = () => {
    setCurrentScreen("inbox");
  };

  const handleSelectNotification = (id: number) => {
    setSelectedNotificationId(id);
    setNotifications((prev) =>
      prev.map((n) =>
        n.id === id ? { ...n, isRead: true } : n,
      ),
    );
    setCurrentScreen("notification");
  };

  const handleSelectCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    setCurrentScreen("company");
  };

  const handleBackToDashboard = () => {
    setCurrentScreen("dashboard");
  };

  const handleViewAnalysis = () => {
    setCurrentScreen("analysis");
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
        />
      )}

      {currentScreen === "company" && (
        <CompanyAnalysis
          companyName={selectedCompany}
          onBack={handleBackToDashboard}
        />
      )}

      {currentScreen === "mylist" && (
        <MyCompaniesList
          onBack={handleBackToDashboard}
          onSelectCompany={handleSelectCompany}
        />
      )}

      {currentScreen === "notification" && (
        <NotificationDetail
          onBack={handleBackToDashboard}
          onViewAnalysis={handleViewAnalysis}
        />
      )}

      {currentScreen === "analysis" && (
        <DeepAnalysisDashboard onBack={handleBackToDashboard} />
      )}

      {currentScreen === "inbox" && (
        <NotificationInbox
          notifications={notifications}
          onBack={handleBackToDashboard}
          onSelectNotification={handleSelectNotification}
        />
      )}
    </>
  );
}