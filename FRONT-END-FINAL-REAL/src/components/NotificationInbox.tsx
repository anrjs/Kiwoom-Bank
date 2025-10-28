// NotificationInbox.tsx
import { useEffect, useRef, useState } from "react"; // ❗️ 제거
import { ArrowLeft, Home, Bell, TrendingDown, TrendingUp, AlertCircle } from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";
// import axios from "axios"; // ❗️ 제거

// ❗️ API_BASE, WATCHLIST, POLL_MS 제거

export interface Notification {
  id: number;
  type: "down" | "warning" | "up";
  companyName: string;
  title: string;
  ratingChange?: string;
  newsKeywords: string;
  timestamp: string;
  isRead: boolean;
}

interface NotificationInboxProps {
  notifications: Notification[]; // ❗️ App.tsx로부터 이 배열을 받음
  onBack: () => void;
  onHome: () => void;
  onSelectNotification: (id: number) => void; // ❗️ App.tsx의 상태 변경 함수
}

export function NotificationInbox({
  notifications, // ❗️ props로 받음
  onBack,
  onHome,
  onSelectNotification,
}: NotificationInboxProps) {

  // ❗️ localNotifs, prevGradesRef, getRatingOrder, fetchGrades 및 모든 useEffect 폴링 로직 제거

  // ====== 클릭 시 부모(App.tsx)의 함수 호출 ======
  const handleSelect = (id: number) => {
    // ❗️ 로컬 상태 변경 대신, 부모의 함수를 호출
    onSelectNotification(id);
  };

  // ====== 기존 UI 함수들 유지 ======
  const getTypeIcon = (type: string) => {
    // ... (기존과 동일)
    switch (type) {
      case "down":
        return <TrendingDown className="w-5 h-5 text-red-600" />;
      case "warning":
        return <AlertCircle className="w-5 h-5 text-yellow-600" />;
      case "up":
        return <TrendingUp className="w-5 h-5 text-green-600" />;
      default:
        return <Bell className="w-5 h-5" />;
    }
  };

  const getTypeBadge = (type: string) => {
    // ... (기존과 동일)
    switch (type) {
      case "down":
        return (
          <Badge className="bg-red-100 text-red-700 border-red-200">
            등급 하락
          </Badge>
        );
      case "warning":
        return (
          <Badge className="bg-yellow-100 text-yellow-700 border-yellow-200">
            하락 위험
          </Badge>
        );
      case "up":
        return (
          <Badge className="bg-green-100 text-green-700 border-green-200">
            등급 상승
          </Badge>
        );
      default:
        return null;
    }
  };

  const getCardStyle = (type: string, isRead: boolean) => {
    // ... (기존과 동일)
    const baseStyle = "cursor-pointer transition-all hover:shadow-lg ";
    const readStyle = isRead ? "bg-slate-50 opacity-80 " : "bg-white ";
    if (!isRead) {
      switch (type) {
        case "down":
          return baseStyle + "border-l-4 border-l-red-500 " + readStyle;
        case "warning":
          return baseStyle + "border-l-4 border-l-yellow-500 " + readStyle;
        case "up":
          return baseStyle + "border-l-4 border-l-green-500 " + readStyle;
      }
    }
    return baseStyle + readStyle + "border-l-4 border-l-slate-300";
  };

  // ❗️ UI는 props로 받은 notifications를 직접 사용
  // const list = localNotifs.length ? localNotifs : notifications; // ❗️ 제거

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header (유지) */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        {/* ... (기존 UI와 동일) ... */}
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 flex items-center justify-center">
                <img src={kiwoomLogo} alt="Kiwoom Logo" className="w-full h-full object-contain" />
              </div>
              <span className="text-slate-700">키움은행</span>
            </div>
            
            <div className="h-8 w-px bg-slate-300"></div>
            
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#AD1765] to-[#8B1252] flex items-center justify-center">
                <span className="text-white tracking-tight">ACI</span>
              </div>
              <span className="text-slate-900">AI Credit Insight</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={onHome} variant="ghost" className="text-slate-600">
              <Home className="w-4 h-4 mr-2" />
              처음으로
            </Button>
            <Button onClick={onBack} variant="ghost" className="text-slate-600">
              <ArrowLeft className="w-4 h-4 mr-2" />
              뒤로가기
            </Button>
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Bell className="w-8 h-8 text-[#AD1765]" />
            <h1 className="text-slate-900">알림함</h1>
          </div>
          <p className="text-slate-600">
            신용등급 변동 및 위험 알림 내역을 확인하세요
          </p>
        </div>

        {/* Summary (❗️ list -> notifications로 변경) */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <Card className="p-4">
            <div className="text-slate-600 mb-1">전체 알림</div>
            <div className="text-slate-900">{notifications.length}개</div>
          </Card>
          <Card className="p-4 bg-[#AD1765]/10 border-[#AD1765]/20">
            <div className="text-[#AD1765] mb-1">읽지 않음</div>
            <div className="text-[#AD1765]">
              {notifications.filter((n) => !n.isRead).length}개
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-slate-600 mb-1">읽음</div>
            <div className="text-slate-900">
              {notifications.filter((n) => n.isRead).length}개
            </div>
          </Card>
        </div>

        {/* Notifications List (❗️ list -> notifications로 변경) */}
        <div className="space-y-4">
          {notifications.map((notification, index) => (
            <Card
              key={notification.id}
              className={getCardStyle(notification.type, notification.isRead)}
              onClick={() => handleSelect(notification.id)} // ❗️ 수정된 핸들러
            >
              <div className="p-5">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-10 h-10 rounded-full bg-slate-100 text-slate-700">
                      {notifications.length - index}
                    </div>
                    {/* ... (기존 UI 동일) ... */}
                    {getTypeIcon(notification.type)}
                    {getTypeBadge(notification.type)}
                    {notification.isRead ? (
                      <Badge variant="outline" className="bg-slate-100 text-slate-600">
                        읽음
                      </Badge>
                    ) : (
                      <Badge className="bg-[#AD1765] text-white animate-pulse">
                        읽지 않음
                      </Badge>
                    )}
                  </div>
                  <span className="text-slate-500">{notification.timestamp}</span>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-900">
                      {notification.companyName}
                    </span>
                    {notification.ratingChange && (
                      <span className="text-slate-600 bg-slate-100 px-3 py-1 rounded-lg">
                        {notification.ratingChange}
                      </span>
                    )}
                  </div>
                  {/* ... (기존 UI 동일) ... */}
                  <p className={notification.isRead ? "text-slate-600" : "text-slate-900"}>
                    {notification.title}
                  </p>

                  <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
                    <span className="text-slate-500">키워드:</span>
                    <span className="text-slate-700">{notification.newsKeywords}</span>
                  </div>
                </div>
              </div>
            </Card>
          ))}

          {notifications.length === 0 && (
            <Card className="p-12 text-center">
              <Bell className="w-12 h-12 text-slate-300 mx-auto mb-4" />
              <p className="text-slate-500">알림이 없습니다</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}