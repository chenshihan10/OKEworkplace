import { setActiveTab, getActiveTab } from '../stores/systemStore.js';

export function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
      const tabName = tab.getAttribute('data-tab');
      if (tabName) switchTab(tabName);
    });
  });
}

export function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  
  const content = document.getElementById(`tab-${tabName}`);
  if (content) content.classList.add('active');
  
  // 找到对应 tab 按钮并激活
  document.querySelectorAll('.tab').forEach(el => {
    if (el.getAttribute('data-tab') === tabName) {
      el.classList.add('active');
    }
  });
  
  setActiveTab(tabName);
}

// 挂载到 window 供 HTML onclick 调用
window.switchTab = switchTab;
