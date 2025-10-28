import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Card, CardContent } from "./ui/card";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";

interface LoginPageProps {
  onLogin: () => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username && password) {
      onLogin();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-gray-50 to-slate-100 flex items-center justify-center p-4 relative overflow-hidden">
      {/* Background decorative elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 left-10 w-72 h-72 bg-[#AD1765]/5 rounded-full blur-3xl"></div>
        <div className="absolute bottom-20 right-10 w-96 h-96 bg-slate-300/30 rounded-full blur-3xl"></div>
      </div>

      <Card className="w-full max-w-md shadow-2xl border-slate-200 relative backdrop-blur-sm bg-white/95">
        <CardContent className="pt-10 pb-8 px-8">
          {/* Logo and branding section */}
          <div className="mb-8">
            <div className="flex items-center justify-center gap-6 mb-6">
              {/* ACI Logo */}
              <div className="relative">
                <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-[#AD1765] to-[#8B1252] shadow-lg flex items-center justify-center transform hover:scale-105 transition-transform">
                  <span className="text-white text-3xl tracking-tight">ACI</span>
                </div>
                <div className="absolute -inset-1 bg-gradient-to-br from-[#AD1765] to-[#8B1252] rounded-2xl blur opacity-20 -z-10"></div>
              </div>

              {/* Divider */}
              <div className="h-20 w-px bg-slate-300"></div>

              {/* Kiwoom Bank Logo */}
              <div className="flex flex-col items-center">
                <div className="w-16 h-16 flex items-center justify-center mb-2">
                  <img src={kiwoomLogo} alt="Kiwoom Logo" className="w-full h-full object-contain" />
                </div>
                <span className="text-slate-700 tracking-wide">키움은행</span>
              </div>
            </div>

            {/* Title */}
            <div className="text-center">
              <h1 className="text-slate-900 mb-2">AI Credit Insight</h1>
              <p className="text-slate-600">기업 신용등급 분석 서비스</p>
            </div>
          </div>

          {/* Divider */}
          <div className="h-px bg-gradient-to-r from-transparent via-slate-300 to-transparent mb-8"></div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="username" className="text-slate-700">사용자 아이디</Label>
              <Input
                id="username"
                type="text"
                placeholder="사용자 아이디를 입력하세요"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="bg-white border-slate-300 focus:border-[#AD1765] focus:ring-[#AD1765]/20 transition-all"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-slate-700">비밀번호</Label>
              <Input
                id="password"
                type="password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="bg-white border-slate-300 focus:border-[#AD1765] focus:ring-[#AD1765]/20 transition-all"
              />
            </div>

            <Button
              type="submit"
              className="w-full bg-gradient-to-r from-[#AD1765] to-[#8B1252] hover:from-[#8B1252] hover:to-[#6E0E42] text-white py-6 shadow-lg hover:shadow-xl transition-all transform hover:scale-[1.02]"
            >
              로그인
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
