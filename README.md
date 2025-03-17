Проект по научно-исследовательскому семинару "Введение в облачные технологии" студентов 1-го курса НИУ ВШЭ ФКН ПИ Загоруйко Даниила Александровича, Окриашвили Константина Гиоргиевича, Малапура Артемия Андреевича
====
# Telegram-бот для сети ресторанов "Coffeemania"
Данный проект представляет собой многофункционального Telegram-бота, разработанного для удобного взаимодействия пользователей с сетью ресторанов "Coffeemania". [Официальная ссылка (ТЫК)](https://t.me/Project_Restaurant_Bot)
## Описание проекта
Telegram-бот предлагает пользователям современные способы взаимодействия с заведением, включая просмотр меню, оформление и оплату заказов, а также персонализированную работу с клиентами через облачные технологии и модульную архитектуру.
## Функциональные требования
### Основные функции
1. **Авторизация:**
   
   - Пользователь авторизуется, предоставляя номер телефона, имя и фамилию.
     
   - Данные сохраняются в облачной базе данных.
     
2. **Выбор ресторана:**
   
   - Возможность выбора ресторана из общей сети "Coffeemania".
     
   - Просмотр актуального меню и информации для конкретного заведения.
     
3. **Просмотр меню:**
   
   - Отображение полного меню с фильтрацией по категориям (напитки, блюда, десерты и др.).
     
4. **Описание блюд:**
   
   - Подробная информация о составе, калорийности, аллергенах и способе приготовления.
     
5. **История заказов:**
   
   - Просмотр истории заказов (дата, заказанные блюда, общая стоимость).
     
   - Хранение истории заказов в облачной базе данных.
     
6. **Оплата заказов:**
   
   - Интеграция с онлайн-системами платежей для оплаты заказов непосредственно через Telegram.
     
## Нефункциональные требования


1. **Надёжность:**

   - Бот должен стабильно работать с минимальным временем простоя.

2. **Производительность:**

   - Высокая скорость обработки запросов пользователей.

3. **Масштабируемость:**

   - Возможность масштабирования на увеличение числа пользователей и ресторанов.
  
4. **Безопасность:**

   - Защита персональных данных пользователей с использованием облачных решений.
  
5. **Удобство использования:**

   - Интуитивно понятный интерфейс, доступный пользователям всех возрастных категорий.
  
## Используемые технологии

- Python

- Telegram Bot API

- Docker

- Облачные сервисы (база данных, хранение данных) 

- CI/CD (GitHub Actions)

[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=github-actions&logoColor=white)](#) [![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](#) [![Postgres](https://img.shields.io/badge/Postgres-%23316192.svg?logo=postgresql&logoColor=white)](#) 
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff)](#) [![Ubuntu](https://img.shields.io/badge/Ubuntu-E95420?logo=ubuntu&logoColor=white)](#)


## Немного про базу данных и виртуальную машину
База данных развернута на ВМ от Yandex.Cloud

Немного про параметры виртуальной машины:

- Платформа: Intel Ice Lake
- RAM: 2 GB
- Объем диска: 20 GB

Параметры не особо крутые, но для такого проекта данная машина подходит отлично! В будущем можно будет сделать резервное копирование, если захотим вывести данного бота "в массы".

База данных работает на СУБД **PostgreSQL**, что делает ее достаточно простой в управлении.

## Контейнерезация и сборка проекта
### Какие файлы содержит?
- **Dockerfile** – описывает процесс сборки Docker-образа
- **docker-compose.yml** – определяет сервисы для запуска приложения в контейнере
- **cicd.yml** 

## Проект автоматически собирается и разворачивается при помощи GitHub Actions:

В этом проекте не требуется локальная сборка. Весь процесс сборки и деплоя полностью автоматизирован с помощью GitHub Actions

- **Разработчику достаточно совершить push в ветку `main`** – после этого автоматически запускается CI/CD Pipeline.
- **CI/CD Pipeline выполняет следующие шаги:**
  - Клонирует репозиторий
  - Собирает новый Docker-образ с последними изменениями
  - Пушит образ в Docker Hub
  - Создаёт или обновляет файл с переменными окружения на сервере
  - Копирует обновлённый (если конечно обновили) `docker-compose.yml` на сервер
  - Останавливает старый контейнер (предыдущей сборки) и запускает новый с обновлённым образом

Таким образом **программа собирается и разворачивается автоматически** – никакие дополнительные действия локальной сборки не требуются и **это важно понимать**!

## Команда
Общей задачей команды была разработка основной логики Telegram-бота, ведь именно с этого начинается успешный проект!!

### Загоруйко Даниил Александрович
**Роль:** Team Lead, backend-разработчик, тестирование  
**Обязанности:**
- Общее руководство проектом, распределение задач и контроль их выполнения
- Интеграция с облачной базой данных.
- Реализация модуля авторизации и хранения данных пользователей
- Тестирование функциональности бота и модулей
- Разработка парсера блюд и винной карты
- Интеграция с платежными системами (оплата заказов)
- Координация работы команды и решение технических проблем\
**Технологии:** Python, PostgreSQL, SQLAlchemy, Git

---

### Окриашвили Константин Гиоргиевич
**Роль:** Backend-разработчик, DevOps  
**Обязанности:**
- Разработка клиентской части бота (`client.py`).
- Развертывание базы данных на виртуальной машине
- Реализация модуля авторизации
- Настройка ВМ, используя Linux
- Настройка Docker-контейнеров для разработки и деплоя
- Написание CI/CD пайплайна
- Поддержка инфраструктуры проекта
**Технологии:** Python, Telegram Bot API, Docker, GitHub Actions, PostgreSQL, Linux, Git

---

### Малапура Артемий Андреевич
**Роль:** Backend-разработчик, тестирование  
**Обязанности:**
- Реализация модуля **истории заказов**
- Разработка парсера для ресторанов для обновления данных
- Тестирование функциональности бота и модулей
- Участие в написании документации \
**Технологии:** Python, Telegram Bot API, Git.

---
