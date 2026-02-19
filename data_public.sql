--
-- PostgreSQL database dump
--

\restrict ntSPPmpHcdLdAv1BXYA3YGBzwyCiQIYbxvSFl0Pd0XOv5tpvlNROBthaxh77baZ

-- Dumped from database version 16.12 (Ubuntu 16.12-1.pgdg24.04+1)
-- Dumped by pg_dump version 18.2 (Ubuntu 18.2-1.pgdg24.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY public.tenant_invoice_settings DROP CONSTRAINT IF EXISTS tenant_invoice_setti_company_id_7a293fb7_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.tenant_email_settings DROP CONSTRAINT IF EXISTS tenant_email_setting_company_id_76056869_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.tenant_domains DROP CONSTRAINT IF EXISTS tenant_domains_tenant_id_6d1ef00b_fk_company_company_company_id;
ALTER TABLE IF EXISTS ONLY public.public_user_activities DROP CONSTRAINT IF EXISTS public_user_activities_user_id_af52c908_fk_public_users_id;
ALTER TABLE IF EXISTS ONLY public.public_tenant_notification_log DROP CONSTRAINT IF EXISTS public_tenant_notifi_signup_request_id_d58a838e_fk_public_te;
ALTER TABLE IF EXISTS ONLY public.public_tenant_approval_workflow DROP CONSTRAINT IF EXISTS public_tenant_approv_signup_request_id_ac3c96b4_fk_public_te;
ALTER TABLE IF EXISTS ONLY public.public_tenant_approval_workflow DROP CONSTRAINT IF EXISTS public_tenant_approv_reviewed_by_id_0689d809_fk_public_us;
ALTER TABLE IF EXISTS ONLY public.public_support_replies DROP CONSTRAINT IF EXISTS public_support_repli_ticket_id_0bc90f02_fk_public_su;
ALTER TABLE IF EXISTS ONLY public.public_seo_ranking_history DROP CONSTRAINT IF EXISTS public_seo_ranking_h_keyword_tracking_id_250ed7e6_fk_public_se;
ALTER TABLE IF EXISTS ONLY public.public_seo_audits DROP CONSTRAINT IF EXISTS public_seo_audits_page_id_2991d684_fk_public_seo_pages_id;
ALTER TABLE IF EXISTS ONLY public.public_password_reset_tokens DROP CONSTRAINT IF EXISTS public_password_rese_user_id_4aeb9d7d_fk_public_us;
ALTER TABLE IF EXISTS ONLY public.public_blog_posts DROP CONSTRAINT IF EXISTS public_blog_posts_category_id_f060c64b_fk_public_bl;
ALTER TABLE IF EXISTS ONLY public.public_blog_comments DROP CONSTRAINT IF EXISTS public_blog_comments_post_id_a93f78ae_fk_public_blog_posts_id;
ALTER TABLE IF EXISTS ONLY public.primebooks_updatelog DROP CONSTRAINT IF EXISTS primebooks_updatelog_version_id_7364cf6f_fk_primebook;
ALTER TABLE IF EXISTS ONLY public.primebooks_maintenancewindow DROP CONSTRAINT IF EXISTS primebooks_maintenan_version_id_92901ac5_fk_primebook;
ALTER TABLE IF EXISTS ONLY public.primebooks_errorreport DROP CONSTRAINT IF EXISTS primebooks_errorrepo_app_version_id_78838568_fk_primebook;
ALTER TABLE IF EXISTS ONLY public.primebooks_appversion DROP CONSTRAINT IF EXISTS primebooks_appversio_rollback_target_id_aad417f8_fk_primebook;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_p_solar_id_a87ce72c_fk_django_ce;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_p_interval_id_a8ca27da_fk_django_ce;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_p_crontab_id_d3cba168_fk_django_ce;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_p_clocked_id_47a69f82_fk_django_ce;
ALTER TABLE IF EXISTS ONLY public.company_crosscompanytransaction DROP CONSTRAINT IF EXISTS company_crosscompany_source_company_id_780155ca_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.company_crosscompanytransaction DROP CONSTRAINT IF EXISTS company_crosscompany_destination_company__54932cef_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.company_companyrelationship DROP CONSTRAINT IF EXISTS company_companyrelat_related_company_id_cf18739d_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.company_companyrelationship DROP CONSTRAINT IF EXISTS company_companyrelat_company_id_9af6d45a_fk_company_c;
ALTER TABLE IF EXISTS ONLY public.company_company DROP CONSTRAINT IF EXISTS company_company_plan_id_2c0e5a90_fk_company_subscriptionplan_id;
DROP INDEX IF EXISTS public.tenant_invoice_settings_company_id_7a293fb7_like;
DROP INDEX IF EXISTS public.tenant_email_settings_company_id_76056869_like;
DROP INDEX IF EXISTS public.tenant_domains_tenant_id_6d1ef00b_like;
DROP INDEX IF EXISTS public.tenant_domains_tenant_id_6d1ef00b;
DROP INDEX IF EXISTS public.tenant_domains_domain_bb1a2d78_like;
DROP INDEX IF EXISTS public.public_users_username_85d526ea_like;
DROP INDEX IF EXISTS public.public_users_identifier_4df4d8df_like;
DROP INDEX IF EXISTS public.public_users_email_7ad3fb5d_like;
DROP INDEX IF EXISTS public.public_user_user_id_c0976b_idx;
DROP INDEX IF EXISTS public.public_user_is_acti_d36014_idx;
DROP INDEX IF EXISTS public.public_user_identif_cc919c_idx;
DROP INDEX IF EXISTS public.public_user_email_4d094c_idx;
DROP INDEX IF EXISTS public.public_user_activities_user_id_af52c908;
DROP INDEX IF EXISTS public.public_user_action_3329d1_idx;
DROP INDEX IF EXISTS public.public_tenant_signup_requests_subdomain_ebf310ca_like;
DROP INDEX IF EXISTS public.public_tenant_notification_log_signup_request_id_d58a838e;
DROP INDEX IF EXISTS public.public_tenant_approval_workflow_reviewed_by_id_0689d809;
DROP INDEX IF EXISTS public.public_tena_subdoma_cc0cf0_idx;
DROP INDEX IF EXISTS public.public_tena_status_dcb7f8_idx;
DROP INDEX IF EXISTS public.public_tena_email_de7076_idx;
DROP INDEX IF EXISTS public.public_tena_created_200a5e_idx;
DROP INDEX IF EXISTS public.public_support_tickets_ticket_number_e1f088c7_like;
DROP INDEX IF EXISTS public.public_support_replies_ticket_id_0bc90f02;
DROP INDEX IF EXISTS public.public_support_faq_slug_9f79dc19_like;
DROP INDEX IF EXISTS public.public_supp_ticket__ca9fbb_idx;
DROP INDEX IF EXISTS public.public_supp_status_48b249_idx;
DROP INDEX IF EXISTS public.public_supp_email_d3e6ce_idx;
DROP INDEX IF EXISTS public.public_subdomain_reservations_subdomain_cbac9159_like;
DROP INDEX IF EXISTS public.public_staff_users_username_5d6dd6c9_like;
DROP INDEX IF EXISTS public.public_staff_users_session_token_449764fa_like;
DROP INDEX IF EXISTS public.public_staff_users_email_b1f38794_like;
DROP INDEX IF EXISTS public.public_seo_sitemap_url_path_ff0f6172_like;
DROP INDEX IF EXISTS public.public_seo_redirects_old_path_9fae0416_like;
DROP INDEX IF EXISTS public.public_seo_ranking_history_keyword_tracking_id_250ed7e6;
DROP INDEX IF EXISTS public.public_seo_pages_url_path_58f6ad4d_like;
DROP INDEX IF EXISTS public.public_seo_pages_page_type_27dcd7ba_like;
DROP INDEX IF EXISTS public.public_seo_audits_page_id_2991d684;
DROP INDEX IF EXISTS public.public_password_reset_tokens_user_id_4aeb9d7d;
DROP INDEX IF EXISTS public.public_password_reset_tokens_token_0deedccb_like;
DROP INDEX IF EXISTS public.public_newsletter_subscribers_email_bf336734_like;
DROP INDEX IF EXISTS public.public_blog_status_f3c34d_idx;
DROP INDEX IF EXISTS public.public_blog_slug_e18e60_idx;
DROP INDEX IF EXISTS public.public_blog_posts_slug_f814922d_like;
DROP INDEX IF EXISTS public.public_blog_posts_category_id_f060c64b;
DROP INDEX IF EXISTS public.public_blog_post_id_bc5715_idx;
DROP INDEX IF EXISTS public.public_blog_newsletter_unsubscribe_token_22c0f928_like;
DROP INDEX IF EXISTS public.public_blog_newsletter_email_aa5d3fc7_like;
DROP INDEX IF EXISTS public.public_blog_email_cbb42a_idx;
DROP INDEX IF EXISTS public.public_blog_comments_post_id_a93f78ae;
DROP INDEX IF EXISTS public.public_blog_categories_slug_911b6539_like;
DROP INDEX IF EXISTS public.public_blog_categories_name_f771648b_like;
DROP INDEX IF EXISTS public.public_blog_categor_4918a4_idx;
DROP INDEX IF EXISTS public.public_analytics_sessions_visitor_id_29f21aa3_like;
DROP INDEX IF EXISTS public.public_analytics_sessions_visitor_id_29f21aa3;
DROP INDEX IF EXISTS public.public_analytics_sessions_session_id_59d629c6_like;
DROP INDEX IF EXISTS public.public_analytics_pageviews_visitor_id_8f1581d4_like;
DROP INDEX IF EXISTS public.public_analytics_pageviews_visitor_id_8f1581d4;
DROP INDEX IF EXISTS public.public_analytics_pageviews_viewed_at_03c113a1;
DROP INDEX IF EXISTS public.public_analytics_pageviews_session_id_af2b1c8b_like;
DROP INDEX IF EXISTS public.public_analytics_pageviews_session_id_af2b1c8b;
DROP INDEX IF EXISTS public.public_analytics_events_visitor_id_3654a7ea_like;
DROP INDEX IF EXISTS public.public_analytics_events_visitor_id_3654a7ea;
DROP INDEX IF EXISTS public.public_analytics_events_session_id_b009fb90_like;
DROP INDEX IF EXISTS public.public_analytics_events_session_id_b009fb90;
DROP INDEX IF EXISTS public.public_analytics_events_occurred_at_b85660c5;
DROP INDEX IF EXISTS public.public_analytics_conversions_visitor_id_cee742e4_like;
DROP INDEX IF EXISTS public.public_analytics_conversions_visitor_id_cee742e4;
DROP INDEX IF EXISTS public.public_analytics_conversions_converted_at_36c50fec;
DROP INDEX IF EXISTS public.public_anal_visitor_b9a160_idx;
DROP INDEX IF EXISTS public.public_anal_visitor_6266ef_idx;
DROP INDEX IF EXISTS public.public_anal_visitor_555612_idx;
DROP INDEX IF EXISTS public.public_anal_utm_cam_94c67c_idx;
DROP INDEX IF EXISTS public.public_anal_utm_cam_0f7363_idx;
DROP INDEX IF EXISTS public.public_anal_url_pat_253726_idx;
DROP INDEX IF EXISTS public.public_anal_session_9a8914_idx;
DROP INDEX IF EXISTS public.public_anal_session_782218_idx;
DROP INDEX IF EXISTS public.public_anal_convert_95ff02_idx;
DROP INDEX IF EXISTS public.public_anal_convers_25c958_idx;
DROP INDEX IF EXISTS public.public_anal_categor_1e5f66_idx;
DROP INDEX IF EXISTS public.public_anal_action_e78260_idx;
DROP INDEX IF EXISTS public.primebooks_updatelog_version_id_7364cf6f;
DROP INDEX IF EXISTS public.primebooks_maintenancewindow_version_id_92901ac5;
DROP INDEX IF EXISTS public.primebooks_errorreport_app_version_id_78838568;
DROP INDEX IF EXISTS public.primebooks_appversions_version_c2444891_like;
DROP INDEX IF EXISTS public.primebooks_appversion_version_71c4d2db_like;
DROP INDEX IF EXISTS public.primebooks_appversion_rollback_target_id_aad417f8;
DROP INDEX IF EXISTS public.django_session_session_key_c0390e0f_like;
DROP INDEX IF EXISTS public.django_session_expire_date_a5c62663;
DROP INDEX IF EXISTS public.django_celery_results_taskresult_task_id_de0d95bf_like;
DROP INDEX IF EXISTS public.django_celery_results_groupresult_group_id_a085f1a9_like;
DROP INDEX IF EXISTS public.django_celery_results_chordcounter_group_id_1f70858c_like;
DROP INDEX IF EXISTS public.django_celery_beat_periodictask_solar_id_a87ce72c;
DROP INDEX IF EXISTS public.django_celery_beat_periodictask_name_265a36b7_like;
DROP INDEX IF EXISTS public.django_celery_beat_periodictask_interval_id_a8ca27da;
DROP INDEX IF EXISTS public.django_celery_beat_periodictask_crontab_id_d3cba168;
DROP INDEX IF EXISTS public.django_celery_beat_periodictask_clocked_id_47a69f82;
DROP INDEX IF EXISTS public.django_cele_worker_d54dd8_idx;
DROP INDEX IF EXISTS public.django_cele_task_na_08aec9_idx;
DROP INDEX IF EXISTS public.django_cele_status_9b6201_idx;
DROP INDEX IF EXISTS public.django_cele_date_do_f59aad_idx;
DROP INDEX IF EXISTS public.django_cele_date_do_caae0e_idx;
DROP INDEX IF EXISTS public.django_cele_date_cr_f04a50_idx;
DROP INDEX IF EXISTS public.django_cele_date_cr_bd6c1d_idx;
DROP INDEX IF EXISTS public.company_subscriptionplan_name_82552ca7_like;
DROP INDEX IF EXISTS public.company_efrishscode_parent_code_3c9acc1c_like;
DROP INDEX IF EXISTS public.company_efrishscode_parent_code_3c9acc1c;
DROP INDEX IF EXISTS public.company_efrishscode_hs_code_f8df25bc_like;
DROP INDEX IF EXISTS public.company_efriscommodityca_commodity_category_code_9d3b5fe6_like;
DROP INDEX IF EXISTS public.company_efr_service_962966_idx;
DROP INDEX IF EXISTS public.company_efr_parent__2dbe28_idx;
DROP INDEX IF EXISTS public.company_efr_commodi_53d7a9_idx;
DROP INDEX IF EXISTS public.company_efr_commodi_3ab183_idx;
DROP INDEX IF EXISTS public.company_crosscompanytransaction_source_company_id_780155ca_like;
DROP INDEX IF EXISTS public.company_crosscompanytransaction_source_company_id_780155ca;
DROP INDEX IF EXISTS public.company_crosscompanytransaction_destination_company_id_54932cef;
DROP INDEX IF EXISTS public.company_crosscompanytran_transaction_number_0c4d96ae_like;
DROP INDEX IF EXISTS public.company_crosscompanytran_destination_company_id_54932cef_like;
DROP INDEX IF EXISTS public.company_companyrelationship_related_company_id_cf18739d_like;
DROP INDEX IF EXISTS public.company_companyrelationship_related_company_id_cf18739d;
DROP INDEX IF EXISTS public.company_companyrelationship_company_id_9af6d45a_like;
DROP INDEX IF EXISTS public.company_companyrelationship_company_id_9af6d45a;
DROP INDEX IF EXISTS public.company_company_slug_cefb92db_like;
DROP INDEX IF EXISTS public.company_company_schema_name_b34e24f8_like;
DROP INDEX IF EXISTS public.company_company_plan_id_2c0e5a90;
DROP INDEX IF EXISTS public.company_company_company_id_4ed2ca46_like;
DROP INDEX IF EXISTS public.company_com_trial_e_2695c2_idx;
DROP INDEX IF EXISTS public.company_com_subscri_f24aad_idx;
DROP INDEX IF EXISTS public.company_com_status_c491e8_idx;
DROP INDEX IF EXISTS public.company_com_last_ac_0754c4_idx;
DROP INDEX IF EXISTS public.company_com_efris_l_3e161a_idx;
DROP INDEX IF EXISTS public.company_com_efris_i_aeac99_idx;
DROP INDEX IF EXISTS public.company_com_efris_e_da20b9_idx;
ALTER TABLE IF EXISTS ONLY public.tenant_invoice_settings DROP CONSTRAINT IF EXISTS tenant_invoice_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.tenant_invoice_settings DROP CONSTRAINT IF EXISTS tenant_invoice_settings_company_id_key;
ALTER TABLE IF EXISTS ONLY public.tenant_email_settings DROP CONSTRAINT IF EXISTS tenant_email_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.tenant_email_settings DROP CONSTRAINT IF EXISTS tenant_email_settings_company_id_key;
ALTER TABLE IF EXISTS ONLY public.tenant_domains DROP CONSTRAINT IF EXISTS tenant_domains_pkey;
ALTER TABLE IF EXISTS ONLY public.tenant_domains DROP CONSTRAINT IF EXISTS tenant_domains_domain_key;
ALTER TABLE IF EXISTS ONLY public.public_users DROP CONSTRAINT IF EXISTS public_users_username_key;
ALTER TABLE IF EXISTS ONLY public.public_users DROP CONSTRAINT IF EXISTS public_users_pkey;
ALTER TABLE IF EXISTS ONLY public.public_users DROP CONSTRAINT IF EXISTS public_users_identifier_key;
ALTER TABLE IF EXISTS ONLY public.public_users DROP CONSTRAINT IF EXISTS public_users_email_key;
ALTER TABLE IF EXISTS ONLY public.public_user_activities DROP CONSTRAINT IF EXISTS public_user_activities_pkey;
ALTER TABLE IF EXISTS ONLY public.public_tenant_signup_requests DROP CONSTRAINT IF EXISTS public_tenant_signup_requests_subdomain_key;
ALTER TABLE IF EXISTS ONLY public.public_tenant_signup_requests DROP CONSTRAINT IF EXISTS public_tenant_signup_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.public_tenant_notification_log DROP CONSTRAINT IF EXISTS public_tenant_notification_log_pkey;
ALTER TABLE IF EXISTS ONLY public.public_tenant_approval_workflow DROP CONSTRAINT IF EXISTS public_tenant_approval_workflow_signup_request_id_key;
ALTER TABLE IF EXISTS ONLY public.public_tenant_approval_workflow DROP CONSTRAINT IF EXISTS public_tenant_approval_workflow_pkey;
ALTER TABLE IF EXISTS ONLY public.public_support_tickets DROP CONSTRAINT IF EXISTS public_support_tickets_ticket_number_key;
ALTER TABLE IF EXISTS ONLY public.public_support_tickets DROP CONSTRAINT IF EXISTS public_support_tickets_pkey;
ALTER TABLE IF EXISTS ONLY public.public_support_replies DROP CONSTRAINT IF EXISTS public_support_replies_pkey;
ALTER TABLE IF EXISTS ONLY public.public_support_faq DROP CONSTRAINT IF EXISTS public_support_faq_slug_key;
ALTER TABLE IF EXISTS ONLY public.public_support_faq DROP CONSTRAINT IF EXISTS public_support_faq_pkey;
ALTER TABLE IF EXISTS ONLY public.public_support_contact_requests DROP CONSTRAINT IF EXISTS public_support_contact_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.public_subdomain_reservations DROP CONSTRAINT IF EXISTS public_subdomain_reservations_subdomain_key;
ALTER TABLE IF EXISTS ONLY public.public_subdomain_reservations DROP CONSTRAINT IF EXISTS public_subdomain_reservations_pkey;
ALTER TABLE IF EXISTS ONLY public.public_staff_users DROP CONSTRAINT IF EXISTS public_staff_users_username_key;
ALTER TABLE IF EXISTS ONLY public.public_staff_users DROP CONSTRAINT IF EXISTS public_staff_users_session_token_key;
ALTER TABLE IF EXISTS ONLY public.public_staff_users DROP CONSTRAINT IF EXISTS public_staff_users_pkey;
ALTER TABLE IF EXISTS ONLY public.public_staff_users DROP CONSTRAINT IF EXISTS public_staff_users_email_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_sitemap DROP CONSTRAINT IF EXISTS public_seo_sitemap_url_path_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_sitemap DROP CONSTRAINT IF EXISTS public_seo_sitemap_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_robots DROP CONSTRAINT IF EXISTS public_seo_robots_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_robots DROP CONSTRAINT IF EXISTS public_seo_robots_is_active_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_redirects DROP CONSTRAINT IF EXISTS public_seo_redirects_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_redirects DROP CONSTRAINT IF EXISTS public_seo_redirects_old_path_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_ranking_history DROP CONSTRAINT IF EXISTS public_seo_ranking_history_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_pages DROP CONSTRAINT IF EXISTS public_seo_pages_url_path_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_pages DROP CONSTRAINT IF EXISTS public_seo_pages_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_pages DROP CONSTRAINT IF EXISTS public_seo_pages_page_type_key;
ALTER TABLE IF EXISTS ONLY public.public_seo_keyword_tracking DROP CONSTRAINT IF EXISTS public_seo_keyword_tracking_pkey;
ALTER TABLE IF EXISTS ONLY public.public_seo_keyword_tracking DROP CONSTRAINT IF EXISTS public_seo_keyword_tracking_keyword_target_url_4c87e2a8_uniq;
ALTER TABLE IF EXISTS ONLY public.public_seo_audits DROP CONSTRAINT IF EXISTS public_seo_audits_pkey;
ALTER TABLE IF EXISTS ONLY public.public_password_reset_tokens DROP CONSTRAINT IF EXISTS public_password_reset_tokens_token_key;
ALTER TABLE IF EXISTS ONLY public.public_password_reset_tokens DROP CONSTRAINT IF EXISTS public_password_reset_tokens_pkey;
ALTER TABLE IF EXISTS ONLY public.public_newsletter_subscribers DROP CONSTRAINT IF EXISTS public_newsletter_subscribers_pkey;
ALTER TABLE IF EXISTS ONLY public.public_newsletter_subscribers DROP CONSTRAINT IF EXISTS public_newsletter_subscribers_email_key;
ALTER TABLE IF EXISTS ONLY public.public_blog_posts DROP CONSTRAINT IF EXISTS public_blog_posts_slug_key;
ALTER TABLE IF EXISTS ONLY public.public_blog_posts DROP CONSTRAINT IF EXISTS public_blog_posts_pkey;
ALTER TABLE IF EXISTS ONLY public.public_blog_newsletter DROP CONSTRAINT IF EXISTS public_blog_newsletter_unsubscribe_token_key;
ALTER TABLE IF EXISTS ONLY public.public_blog_newsletter DROP CONSTRAINT IF EXISTS public_blog_newsletter_pkey;
ALTER TABLE IF EXISTS ONLY public.public_blog_newsletter DROP CONSTRAINT IF EXISTS public_blog_newsletter_email_key;
ALTER TABLE IF EXISTS ONLY public.public_blog_comments DROP CONSTRAINT IF EXISTS public_blog_comments_pkey;
ALTER TABLE IF EXISTS ONLY public.public_blog_categories DROP CONSTRAINT IF EXISTS public_blog_categories_slug_key;
ALTER TABLE IF EXISTS ONLY public.public_blog_categories DROP CONSTRAINT IF EXISTS public_blog_categories_pkey;
ALTER TABLE IF EXISTS ONLY public.public_blog_categories DROP CONSTRAINT IF EXISTS public_blog_categories_name_key;
ALTER TABLE IF EXISTS ONLY public.public_analytics_sessions DROP CONSTRAINT IF EXISTS public_analytics_sessions_session_id_key;
ALTER TABLE IF EXISTS ONLY public.public_analytics_sessions DROP CONSTRAINT IF EXISTS public_analytics_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.public_analytics_pageviews DROP CONSTRAINT IF EXISTS public_analytics_pageviews_pkey;
ALTER TABLE IF EXISTS ONLY public.public_analytics_events DROP CONSTRAINT IF EXISTS public_analytics_events_pkey;
ALTER TABLE IF EXISTS ONLY public.public_analytics_daily_stats DROP CONSTRAINT IF EXISTS public_analytics_daily_stats_pkey;
ALTER TABLE IF EXISTS ONLY public.public_analytics_daily_stats DROP CONSTRAINT IF EXISTS public_analytics_daily_stats_date_key;
ALTER TABLE IF EXISTS ONLY public.public_analytics_conversions DROP CONSTRAINT IF EXISTS public_analytics_conversions_pkey;
ALTER TABLE IF EXISTS ONLY public.primebooks_updatelog DROP CONSTRAINT IF EXISTS primebooks_updatelog_pkey;
ALTER TABLE IF EXISTS ONLY public.primebooks_maintenancewindow DROP CONSTRAINT IF EXISTS primebooks_maintenancewindow_pkey;
ALTER TABLE IF EXISTS ONLY public.primebooks_errorreport DROP CONSTRAINT IF EXISTS primebooks_errorreport_pkey;
ALTER TABLE IF EXISTS ONLY public.primebooks_appversions DROP CONSTRAINT IF EXISTS primebooks_appversions_version_key;
ALTER TABLE IF EXISTS ONLY public.primebooks_appversions DROP CONSTRAINT IF EXISTS primebooks_appversions_pkey;
ALTER TABLE IF EXISTS ONLY public.primebooks_appversion DROP CONSTRAINT IF EXISTS primebooks_appversion_version_key;
ALTER TABLE IF EXISTS ONLY public.primebooks_appversion DROP CONSTRAINT IF EXISTS primebooks_appversion_pkey;
ALTER TABLE IF EXISTS ONLY public.django_session DROP CONSTRAINT IF EXISTS django_session_pkey;
ALTER TABLE IF EXISTS ONLY public.django_migrations DROP CONSTRAINT IF EXISTS django_migrations_pkey;
ALTER TABLE IF EXISTS ONLY public.django_content_type DROP CONSTRAINT IF EXISTS django_content_type_pkey;
ALTER TABLE IF EXISTS ONLY public.django_content_type DROP CONSTRAINT IF EXISTS django_content_type_app_label_model_76bd3d3b_uniq;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_taskresult DROP CONSTRAINT IF EXISTS django_celery_results_taskresult_task_id_key;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_taskresult DROP CONSTRAINT IF EXISTS django_celery_results_taskresult_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_groupresult DROP CONSTRAINT IF EXISTS django_celery_results_groupresult_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_groupresult DROP CONSTRAINT IF EXISTS django_celery_results_groupresult_group_id_key;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_chordcounter DROP CONSTRAINT IF EXISTS django_celery_results_chordcounter_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_results_chordcounter DROP CONSTRAINT IF EXISTS django_celery_results_chordcounter_group_id_key;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_solarschedule DROP CONSTRAINT IF EXISTS django_celery_beat_solarschedule_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_solarschedule DROP CONSTRAINT IF EXISTS django_celery_beat_solar_event_latitude_longitude_ba64999a_uniq;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictasks DROP CONSTRAINT IF EXISTS django_celery_beat_periodictasks_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_periodictask_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_periodictask DROP CONSTRAINT IF EXISTS django_celery_beat_periodictask_name_key;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_intervalschedule DROP CONSTRAINT IF EXISTS django_celery_beat_intervalschedule_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_crontabschedule DROP CONSTRAINT IF EXISTS django_celery_beat_crontabschedule_pkey;
ALTER TABLE IF EXISTS ONLY public.django_celery_beat_clockedschedule DROP CONSTRAINT IF EXISTS django_celery_beat_clockedschedule_pkey;
ALTER TABLE IF EXISTS ONLY public.company_subscriptionplan DROP CONSTRAINT IF EXISTS company_subscriptionplan_pkey;
ALTER TABLE IF EXISTS ONLY public.company_subscriptionplan DROP CONSTRAINT IF EXISTS company_subscriptionplan_name_key;
ALTER TABLE IF EXISTS ONLY public.company_efrishscode DROP CONSTRAINT IF EXISTS company_efrishscode_pkey;
ALTER TABLE IF EXISTS ONLY public.company_efrishscode DROP CONSTRAINT IF EXISTS company_efrishscode_hs_code_key;
ALTER TABLE IF EXISTS ONLY public.company_efriscommoditycategory DROP CONSTRAINT IF EXISTS company_efriscommoditycategory_pkey;
ALTER TABLE IF EXISTS ONLY public.company_efriscommoditycategory DROP CONSTRAINT IF EXISTS company_efriscommoditycategory_commodity_category_code_key;
ALTER TABLE IF EXISTS ONLY public.company_crosscompanytransaction DROP CONSTRAINT IF EXISTS company_crosscompanytransaction_transaction_number_key;
ALTER TABLE IF EXISTS ONLY public.company_crosscompanytransaction DROP CONSTRAINT IF EXISTS company_crosscompanytransaction_pkey;
ALTER TABLE IF EXISTS ONLY public.company_companyrelationship DROP CONSTRAINT IF EXISTS company_companyrelationship_pkey;
ALTER TABLE IF EXISTS ONLY public.company_companyrelationship DROP CONSTRAINT IF EXISTS company_companyrelations_company_id_related_compa_b84ef8a0_uniq;
ALTER TABLE IF EXISTS ONLY public.company_company DROP CONSTRAINT IF EXISTS company_company_slug_key;
ALTER TABLE IF EXISTS ONLY public.company_company DROP CONSTRAINT IF EXISTS company_company_schema_name_key;
ALTER TABLE IF EXISTS ONLY public.company_company DROP CONSTRAINT IF EXISTS company_company_pkey;
DROP TABLE IF EXISTS public.tenant_invoice_settings;
DROP TABLE IF EXISTS public.tenant_email_settings;
DROP TABLE IF EXISTS public.tenant_domains;
DROP TABLE IF EXISTS public.public_users;
DROP TABLE IF EXISTS public.public_user_activities;
DROP TABLE IF EXISTS public.public_tenant_signup_requests;
DROP TABLE IF EXISTS public.public_tenant_notification_log;
DROP TABLE IF EXISTS public.public_tenant_approval_workflow;
DROP TABLE IF EXISTS public.public_support_tickets;
DROP TABLE IF EXISTS public.public_support_replies;
DROP TABLE IF EXISTS public.public_support_faq;
DROP TABLE IF EXISTS public.public_support_contact_requests;
DROP TABLE IF EXISTS public.public_subdomain_reservations;
DROP TABLE IF EXISTS public.public_staff_users;
DROP TABLE IF EXISTS public.public_seo_sitemap;
DROP TABLE IF EXISTS public.public_seo_robots;
DROP TABLE IF EXISTS public.public_seo_redirects;
DROP TABLE IF EXISTS public.public_seo_ranking_history;
DROP TABLE IF EXISTS public.public_seo_pages;
DROP TABLE IF EXISTS public.public_seo_keyword_tracking;
DROP TABLE IF EXISTS public.public_seo_audits;
DROP TABLE IF EXISTS public.public_password_reset_tokens;
DROP TABLE IF EXISTS public.public_newsletter_subscribers;
DROP TABLE IF EXISTS public.public_blog_posts;
DROP TABLE IF EXISTS public.public_blog_newsletter;
DROP TABLE IF EXISTS public.public_blog_comments;
DROP TABLE IF EXISTS public.public_blog_categories;
DROP TABLE IF EXISTS public.public_analytics_sessions;
DROP TABLE IF EXISTS public.public_analytics_pageviews;
DROP TABLE IF EXISTS public.public_analytics_events;
DROP TABLE IF EXISTS public.public_analytics_daily_stats;
DROP TABLE IF EXISTS public.public_analytics_conversions;
DROP TABLE IF EXISTS public.primebooks_updatelog;
DROP TABLE IF EXISTS public.primebooks_maintenancewindow;
DROP TABLE IF EXISTS public.primebooks_errorreport;
DROP TABLE IF EXISTS public.primebooks_appversions;
DROP TABLE IF EXISTS public.primebooks_appversion;
DROP TABLE IF EXISTS public.django_session;
DROP TABLE IF EXISTS public.django_migrations;
DROP TABLE IF EXISTS public.django_content_type;
DROP TABLE IF EXISTS public.django_celery_results_taskresult;
DROP TABLE IF EXISTS public.django_celery_results_groupresult;
DROP TABLE IF EXISTS public.django_celery_results_chordcounter;
DROP TABLE IF EXISTS public.django_celery_beat_solarschedule;
DROP TABLE IF EXISTS public.django_celery_beat_periodictasks;
DROP TABLE IF EXISTS public.django_celery_beat_periodictask;
DROP TABLE IF EXISTS public.django_celery_beat_intervalschedule;
DROP TABLE IF EXISTS public.django_celery_beat_crontabschedule;
DROP TABLE IF EXISTS public.django_celery_beat_clockedschedule;
DROP TABLE IF EXISTS public.company_subscriptionplan;
DROP TABLE IF EXISTS public.company_efrishscode;
DROP TABLE IF EXISTS public.company_efriscommoditycategory;
DROP TABLE IF EXISTS public.company_crosscompanytransaction;
DROP TABLE IF EXISTS public.company_companyrelationship;
DROP TABLE IF EXISTS public.company_company;
DROP FUNCTION IF EXISTS public.auto_fix_sequence();
DROP SCHEMA IF EXISTS public;
--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: auto_fix_sequence(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.auto_fix_sequence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
                DECLARE
                           seq_name TEXT;
                    max_id
                           BIGINT;
                           BEGIN
                    seq_name
                           := pg_get_serial_sequence(TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, 'id');

                    IF
                           seq_name IS NOT NULL THEN
                        EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I', 
                                      TG_TABLE_SCHEMA, TG_TABLE_NAME) INTO max_id;
                           EXECUTE format('SELECT setval(%L, GREATEST(%s, 1), true)',
                                          seq_name, max_id);
                           END IF;

                           RETURN NEW;
                           END;
                $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: company_company; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_company (
    company_id character varying(10) NOT NULL,
    schema_name character varying(63) NOT NULL,
    name character varying(255) NOT NULL,
    trading_name character varying(255),
    slug character varying(50) NOT NULL,
    description text NOT NULL,
    physical_address text NOT NULL,
    postal_address character varying(255),
    phone character varying(20) NOT NULL,
    email character varying(400) NOT NULL,
    website character varying(200),
    tin character varying(20),
    brn character varying(20),
    nin character varying(20),
    preferred_currency character varying(3) NOT NULL,
    efris_enabled boolean NOT NULL,
    efris_is_production boolean NOT NULL,
    efris_integration_mode character varying(10) NOT NULL,
    efris_device_number character varying(50),
    efris_certificate_data jsonb NOT NULL,
    efris_auto_fiscalize_sales boolean NOT NULL,
    efris_auto_sync_products boolean NOT NULL,
    efris_is_active boolean NOT NULL,
    efris_is_registered boolean NOT NULL,
    efris_last_sync timestamp with time zone,
    certificate_status character varying(50),
    status character varying(20) NOT NULL,
    is_trial boolean NOT NULL,
    trial_ends_at date,
    subscription_starts_at date,
    subscription_ends_at date,
    grace_period_ends_at date,
    last_payment_date date,
    next_billing_date date,
    payment_method character varying(50),
    billing_email character varying(254),
    time_zone character varying(100) NOT NULL,
    locale character varying(10) NOT NULL,
    date_format character varying(20) NOT NULL,
    time_format character varying(10) NOT NULL,
    logo character varying(100),
    favicon character varying(100),
    brand_colors jsonb NOT NULL,
    is_verified boolean NOT NULL,
    verification_token character varying(100),
    two_factor_required boolean NOT NULL,
    ip_whitelist jsonb NOT NULL,
    storage_used_mb integer NOT NULL,
    api_calls_this_month integer NOT NULL,
    last_activity_at timestamp with time zone,
    notes text NOT NULL,
    tags jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_active boolean NOT NULL,
    created_on timestamp with time zone NOT NULL,
    plan_id bigint,
    is_vat_enabled boolean NOT NULL,
    CONSTRAINT company_company_api_calls_this_month_check CHECK ((api_calls_this_month >= 0)),
    CONSTRAINT company_company_storage_used_mb_check CHECK ((storage_used_mb >= 0))
);


--
-- Name: company_companyrelationship; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_companyrelationship (
    id bigint NOT NULL,
    relationship_type character varying(20) NOT NULL,
    credit_limit numeric(15,2) NOT NULL,
    payment_terms_days integer NOT NULL,
    is_active boolean NOT NULL,
    notes text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    company_id character varying(10) NOT NULL,
    related_company_id character varying(10) NOT NULL
);


--
-- Name: company_companyrelationship_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_companyrelationship ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.company_companyrelationship_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_crosscompanytransaction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_crosscompanytransaction (
    id bigint NOT NULL,
    transaction_number character varying(50) NOT NULL,
    transaction_type character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    transaction_data jsonb NOT NULL,
    source_reference_id character varying(50) NOT NULL,
    destination_reference_id character varying(50) NOT NULL,
    total_amount numeric(15,2) NOT NULL,
    currency character varying(3) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    destination_company_id character varying(10) NOT NULL,
    source_company_id character varying(10) NOT NULL
);


--
-- Name: company_crosscompanytransaction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_crosscompanytransaction ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.company_crosscompanytransaction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_efriscommoditycategory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_efriscommoditycategory (
    id bigint NOT NULL,
    commodity_category_code character varying(18) NOT NULL,
    parent_code character varying(18),
    commodity_category_name character varying(200) NOT NULL,
    commodity_category_level character varying(5),
    rate numeric(5,2),
    service_mark character varying(3) NOT NULL,
    is_leaf_node character varying(3) NOT NULL,
    is_zero_rate character varying(3) NOT NULL,
    zero_rate_start_date character varying(20),
    zero_rate_end_date character varying(20),
    is_exempt character varying(3) NOT NULL,
    exempt_rate_start_date character varying(20),
    exempt_rate_end_date character varying(20),
    enable_status_code character varying(3),
    exclusion character varying(3),
    last_synced timestamp with time zone NOT NULL
);


--
-- Name: company_efriscommoditycategory_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_efriscommoditycategory ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.company_efriscommoditycategory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_efrishscode; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_efrishscode (
    id bigint NOT NULL,
    hs_code character varying(20) NOT NULL,
    description text NOT NULL,
    parent_code character varying(20),
    is_leaf boolean NOT NULL,
    last_synced timestamp with time zone NOT NULL
);


--
-- Name: company_efrishscode_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_efrishscode ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.company_efrishscode_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_subscriptionplan; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_subscriptionplan (
    id bigint NOT NULL,
    name character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text NOT NULL,
    price numeric(10,2) NOT NULL,
    setup_fee numeric(8,2) NOT NULL,
    billing_cycle character varying(20) NOT NULL,
    trial_days integer NOT NULL,
    max_users integer NOT NULL,
    max_branches integer NOT NULL,
    max_storage_gb integer NOT NULL,
    max_api_calls_per_month integer NOT NULL,
    max_transactions_per_month integer NOT NULL,
    features jsonb NOT NULL,
    can_use_api boolean NOT NULL,
    can_export_data boolean NOT NULL,
    can_use_integrations boolean NOT NULL,
    can_use_advanced_reports boolean NOT NULL,
    can_use_multi_currency boolean NOT NULL,
    can_use_custom_branding boolean NOT NULL,
    support_level character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    is_popular boolean NOT NULL,
    sort_order integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT company_subscriptionplan_max_api_calls_per_month_check CHECK ((max_api_calls_per_month >= 0)),
    CONSTRAINT company_subscriptionplan_max_branches_check CHECK ((max_branches >= 0)),
    CONSTRAINT company_subscriptionplan_max_storage_gb_check CHECK ((max_storage_gb >= 0)),
    CONSTRAINT company_subscriptionplan_max_transactions_per_month_check CHECK ((max_transactions_per_month >= 0)),
    CONSTRAINT company_subscriptionplan_max_users_check CHECK ((max_users >= 0)),
    CONSTRAINT company_subscriptionplan_sort_order_check CHECK ((sort_order >= 0)),
    CONSTRAINT company_subscriptionplan_trial_days_check CHECK ((trial_days >= 0))
);


--
-- Name: company_subscriptionplan_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_subscriptionplan ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.company_subscriptionplan_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_beat_clockedschedule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_clockedschedule (
    id integer NOT NULL,
    clocked_time timestamp with time zone NOT NULL
);


--
-- Name: django_celery_beat_clockedschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_beat_clockedschedule ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_beat_clockedschedule_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_beat_crontabschedule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_crontabschedule (
    id integer NOT NULL,
    minute character varying(240) NOT NULL,
    hour character varying(96) NOT NULL,
    day_of_week character varying(64) NOT NULL,
    day_of_month character varying(124) NOT NULL,
    month_of_year character varying(64) NOT NULL,
    timezone character varying(63) NOT NULL
);


--
-- Name: django_celery_beat_crontabschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_beat_crontabschedule ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_beat_crontabschedule_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_beat_intervalschedule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_intervalschedule (
    id integer NOT NULL,
    every integer NOT NULL,
    period character varying(24) NOT NULL
);


--
-- Name: django_celery_beat_intervalschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_beat_intervalschedule ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_beat_intervalschedule_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_beat_periodictask; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_periodictask (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    task character varying(200) NOT NULL,
    args text NOT NULL,
    kwargs text NOT NULL,
    queue character varying(200),
    exchange character varying(200),
    routing_key character varying(200),
    expires timestamp with time zone,
    enabled boolean NOT NULL,
    last_run_at timestamp with time zone,
    total_run_count integer NOT NULL,
    date_changed timestamp with time zone NOT NULL,
    description text NOT NULL,
    crontab_id integer,
    interval_id integer,
    solar_id integer,
    one_off boolean NOT NULL,
    start_time timestamp with time zone,
    priority integer,
    headers text NOT NULL,
    clocked_id integer,
    expire_seconds integer,
    CONSTRAINT django_celery_beat_periodictask_expire_seconds_check CHECK ((expire_seconds >= 0)),
    CONSTRAINT django_celery_beat_periodictask_priority_check CHECK ((priority >= 0)),
    CONSTRAINT django_celery_beat_periodictask_total_run_count_check CHECK ((total_run_count >= 0))
);


--
-- Name: django_celery_beat_periodictask_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_beat_periodictask ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_beat_periodictask_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_beat_periodictasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_periodictasks (
    ident smallint NOT NULL,
    last_update timestamp with time zone NOT NULL
);


--
-- Name: django_celery_beat_solarschedule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_beat_solarschedule (
    id integer NOT NULL,
    event character varying(24) NOT NULL,
    latitude numeric(9,6) NOT NULL,
    longitude numeric(9,6) NOT NULL
);


--
-- Name: django_celery_beat_solarschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_beat_solarschedule ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_beat_solarschedule_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_results_chordcounter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_results_chordcounter (
    id integer NOT NULL,
    group_id character varying(255) NOT NULL,
    sub_tasks text NOT NULL,
    count integer NOT NULL,
    CONSTRAINT django_celery_results_chordcounter_count_check CHECK ((count >= 0))
);


--
-- Name: django_celery_results_chordcounter_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_results_chordcounter ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_results_chordcounter_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_results_groupresult; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_results_groupresult (
    id integer NOT NULL,
    group_id character varying(255) NOT NULL,
    date_created timestamp with time zone NOT NULL,
    date_done timestamp with time zone NOT NULL,
    content_type character varying(128) NOT NULL,
    content_encoding character varying(64) NOT NULL,
    result text
);


--
-- Name: django_celery_results_groupresult_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_results_groupresult ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_results_groupresult_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_celery_results_taskresult; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_celery_results_taskresult (
    id integer NOT NULL,
    task_id character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    content_type character varying(128) NOT NULL,
    content_encoding character varying(64) NOT NULL,
    result text,
    date_done timestamp with time zone NOT NULL,
    traceback text,
    meta text,
    task_args text,
    task_kwargs text,
    task_name character varying(255),
    worker character varying(100),
    date_created timestamp with time zone NOT NULL,
    periodic_task_name character varying(255)
);


--
-- Name: django_celery_results_taskresult_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_celery_results_taskresult ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_celery_results_taskresult_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: primebooks_appversion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primebooks_appversion (
    id bigint NOT NULL,
    version character varying(20) NOT NULL,
    release_date timestamp with time zone NOT NULL,
    release_notes text NOT NULL,
    lifecycle_status character varying(20) NOT NULL,
    active_date timestamp with time zone NOT NULL,
    stable_date timestamp with time zone,
    deprecated_date timestamp with time zone,
    eol_date timestamp with time zone,
    is_critical boolean NOT NULL,
    deprecation_warning text NOT NULL,
    eol_warning text NOT NULL,
    requires_rollback boolean NOT NULL,
    rollback_reason text NOT NULL,
    rollback_priority character varying(20) NOT NULL,
    windows_file character varying(100),
    linux_file character varying(100),
    mac_file character varying(100),
    file_size_mb numeric(6,2) NOT NULL,
    is_latest boolean NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    rollback_target_id bigint
);


--
-- Name: primebooks_appversion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.primebooks_appversion ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.primebooks_appversion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: primebooks_appversions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primebooks_appversions (
    id bigint NOT NULL,
    version character varying(20) NOT NULL,
    release_date date NOT NULL,
    windows_url character varying(200) NOT NULL,
    mac_url character varying(200) NOT NULL,
    linux_url character varying(200) NOT NULL,
    file_size_mb integer NOT NULL,
    release_notes text NOT NULL,
    is_active boolean NOT NULL,
    is_critical boolean NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: primebooks_appversions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.primebooks_appversions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.primebooks_appversions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: primebooks_errorreport; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primebooks_errorreport (
    id bigint NOT NULL,
    error_type character varying(200) NOT NULL,
    error_message text NOT NULL,
    traceback text NOT NULL,
    os_name character varying(50) NOT NULL,
    os_version character varying(100) NOT NULL,
    python_version character varying(20) NOT NULL,
    logs text NOT NULL,
    system_info jsonb,
    is_critical boolean NOT NULL,
    is_resolved boolean NOT NULL,
    resolution_notes text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    app_version_id bigint
);


--
-- Name: primebooks_errorreport_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.primebooks_errorreport ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.primebooks_errorreport_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: primebooks_maintenancewindow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primebooks_maintenancewindow (
    id bigint NOT NULL,
    title character varying(200) NOT NULL,
    description text NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    notify_24h_before boolean NOT NULL,
    notify_1h_before boolean NOT NULL,
    notification_sent_24h boolean NOT NULL,
    notification_sent_1h boolean NOT NULL,
    is_active boolean NOT NULL,
    is_completed boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    version_id bigint
);


--
-- Name: primebooks_maintenancewindow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.primebooks_maintenancewindow ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.primebooks_maintenancewindow_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: primebooks_updatelog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primebooks_updatelog (
    id bigint NOT NULL,
    download_started timestamp with time zone,
    download_completed timestamp with time zone,
    download_failed boolean NOT NULL,
    download_error text NOT NULL,
    installation_started timestamp with time zone,
    installation_completed timestamp with time zone,
    installation_failed boolean NOT NULL,
    installation_error text NOT NULL,
    platform character varying(20) NOT NULL,
    update_type character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    version_id bigint NOT NULL
);


--
-- Name: primebooks_updatelog_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.primebooks_updatelog ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.primebooks_updatelog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_analytics_conversions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_analytics_conversions (
    id bigint NOT NULL,
    conversion_type character varying(50) NOT NULL,
    conversion_value numeric(10,2),
    visitor_id character varying(64) NOT NULL,
    session_id character varying(64) NOT NULL,
    first_touch_source character varying(100) NOT NULL,
    last_touch_source character varying(100) NOT NULL,
    utm_source character varying(100) NOT NULL,
    utm_medium character varying(100) NOT NULL,
    utm_campaign character varying(100) NOT NULL,
    signup_request_id uuid,
    company_id character varying(10) NOT NULL,
    metadata jsonb NOT NULL,
    converted_at timestamp with time zone NOT NULL
);


--
-- Name: public_analytics_conversions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_analytics_conversions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_analytics_conversions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_analytics_daily_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_analytics_daily_stats (
    id bigint NOT NULL,
    date date NOT NULL,
    unique_visitors integer NOT NULL,
    total_pageviews integer NOT NULL,
    total_sessions integer NOT NULL,
    avg_session_duration double precision NOT NULL,
    avg_pages_per_session double precision NOT NULL,
    bounce_rate double precision NOT NULL,
    signups_started integer NOT NULL,
    signups_completed integer NOT NULL,
    conversion_rate double precision NOT NULL,
    top_pages jsonb NOT NULL,
    top_sources jsonb NOT NULL,
    top_campaigns jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT public_analytics_daily_stats_signups_completed_check CHECK ((signups_completed >= 0)),
    CONSTRAINT public_analytics_daily_stats_signups_started_check CHECK ((signups_started >= 0)),
    CONSTRAINT public_analytics_daily_stats_total_pageviews_check CHECK ((total_pageviews >= 0)),
    CONSTRAINT public_analytics_daily_stats_total_sessions_check CHECK ((total_sessions >= 0)),
    CONSTRAINT public_analytics_daily_stats_unique_visitors_check CHECK ((unique_visitors >= 0))
);


--
-- Name: public_analytics_daily_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_analytics_daily_stats ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_analytics_daily_stats_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_analytics_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_analytics_events (
    id bigint NOT NULL,
    category character varying(50) NOT NULL,
    action character varying(100) NOT NULL,
    label character varying(255) NOT NULL,
    value integer,
    url_path character varying(500) NOT NULL,
    page_title character varying(255) NOT NULL,
    session_id character varying(64) NOT NULL,
    visitor_id character varying(64) NOT NULL,
    metadata jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL
);


--
-- Name: public_analytics_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_analytics_events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_analytics_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_analytics_pageviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_analytics_pageviews (
    id bigint NOT NULL,
    url_path character varying(500) NOT NULL,
    page_title character varying(255) NOT NULL,
    referrer character varying(500) NOT NULL,
    session_id character varying(64) NOT NULL,
    visitor_id character varying(64) NOT NULL,
    ip_address inet NOT NULL,
    user_agent text NOT NULL,
    browser character varying(50) NOT NULL,
    os character varying(50) NOT NULL,
    device_type character varying(20) NOT NULL,
    country character varying(100) NOT NULL,
    city character varying(100) NOT NULL,
    viewed_at timestamp with time zone NOT NULL,
    time_on_page_seconds integer,
    utm_source character varying(100) NOT NULL,
    utm_medium character varying(100) NOT NULL,
    utm_campaign character varying(100) NOT NULL,
    utm_term character varying(100) NOT NULL,
    utm_content character varying(100) NOT NULL,
    CONSTRAINT public_analytics_pageviews_time_on_page_seconds_check CHECK ((time_on_page_seconds >= 0))
);


--
-- Name: public_analytics_pageviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_analytics_pageviews ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_analytics_pageviews_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_analytics_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_analytics_sessions (
    id bigint NOT NULL,
    session_id character varying(64) NOT NULL,
    visitor_id character varying(64) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    last_activity_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone,
    duration_seconds integer,
    entry_page character varying(500) NOT NULL,
    exit_page character varying(500) NOT NULL,
    pages_viewed integer NOT NULL,
    events_count integer NOT NULL,
    converted boolean NOT NULL,
    referrer character varying(500) NOT NULL,
    utm_source character varying(100) NOT NULL,
    utm_medium character varying(100) NOT NULL,
    utm_campaign character varying(100) NOT NULL,
    utm_term character varying(100) NOT NULL,
    utm_content character varying(100) NOT NULL,
    CONSTRAINT public_analytics_sessions_duration_seconds_check CHECK ((duration_seconds >= 0)),
    CONSTRAINT public_analytics_sessions_events_count_check CHECK ((events_count >= 0)),
    CONSTRAINT public_analytics_sessions_pages_viewed_check CHECK ((pages_viewed >= 0))
);


--
-- Name: public_analytics_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_analytics_sessions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_analytics_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_blog_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_blog_categories (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    slug character varying(100) NOT NULL,
    description text NOT NULL,
    meta_title character varying(70) NOT NULL,
    meta_description character varying(160) NOT NULL,
    is_active boolean NOT NULL,
    "order" integer NOT NULL,
    CONSTRAINT public_blog_categories_order_check CHECK (("order" >= 0))
);


--
-- Name: public_blog_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_blog_categories ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_blog_categories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_blog_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_blog_comments (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    email character varying(254) NOT NULL,
    website character varying(200) NOT NULL,
    content text NOT NULL,
    is_approved boolean NOT NULL,
    is_spam boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    approved_at timestamp with time zone,
    ip_address inet,
    user_agent text NOT NULL,
    post_id bigint NOT NULL
);


--
-- Name: public_blog_comments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_blog_comments ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_blog_comments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_blog_newsletter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_blog_newsletter (
    id bigint NOT NULL,
    email character varying(254) NOT NULL,
    name character varying(100) NOT NULL,
    is_active boolean NOT NULL,
    subscribed_from character varying(50) NOT NULL,
    subscribed_at timestamp with time zone NOT NULL,
    unsubscribed_at timestamp with time zone,
    last_email_sent timestamp with time zone,
    unsubscribe_token character varying(64) NOT NULL
);


--
-- Name: public_blog_newsletter_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_blog_newsletter ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_blog_newsletter_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_blog_posts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_blog_posts (
    id bigint NOT NULL,
    title character varying(200) NOT NULL,
    slug character varying(200) NOT NULL,
    excerpt text NOT NULL,
    content text NOT NULL,
    tags character varying(255) NOT NULL,
    featured_image character varying(100),
    featured_image_alt character varying(255) NOT NULL,
    meta_title character varying(70) NOT NULL,
    meta_description character varying(160) NOT NULL,
    focus_keyword character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    published_at timestamp with time zone,
    scheduled_for timestamp with time zone,
    view_count integer NOT NULL,
    reading_time_minutes integer NOT NULL,
    author_name character varying(100) NOT NULL,
    author_email character varying(254) NOT NULL,
    author_bio text NOT NULL,
    author_avatar character varying(100),
    is_featured boolean NOT NULL,
    allow_comments boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    category_id bigint,
    CONSTRAINT public_blog_posts_reading_time_minutes_check CHECK ((reading_time_minutes >= 0)),
    CONSTRAINT public_blog_posts_view_count_check CHECK ((view_count >= 0))
);


--
-- Name: public_blog_posts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_blog_posts ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_blog_posts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_newsletter_subscribers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_newsletter_subscribers (
    id bigint NOT NULL,
    email character varying(254) NOT NULL,
    name character varying(255) NOT NULL,
    subscribed_at timestamp with time zone NOT NULL,
    is_active boolean NOT NULL
);


--
-- Name: public_newsletter_subscribers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_newsletter_subscribers ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_newsletter_subscribers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_password_reset_tokens (
    id bigint NOT NULL,
    token character varying(100) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    is_used boolean NOT NULL,
    used_at timestamp with time zone,
    ip_address inet,
    user_id bigint NOT NULL
);


--
-- Name: public_password_reset_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_password_reset_tokens ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_password_reset_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_audits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_audits (
    id bigint NOT NULL,
    severity character varying(20) NOT NULL,
    issue_type character varying(100) NOT NULL,
    description text NOT NULL,
    recommendation text NOT NULL,
    is_resolved boolean NOT NULL,
    resolved_at timestamp with time zone,
    detected_at timestamp with time zone NOT NULL,
    page_id bigint NOT NULL
);


--
-- Name: public_seo_audits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_audits ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_audits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_keyword_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_keyword_tracking (
    id bigint NOT NULL,
    keyword character varying(200) NOT NULL,
    target_url character varying(200) NOT NULL,
    current_position integer,
    search_volume integer,
    competition character varying(20) NOT NULL,
    tracked_since date NOT NULL,
    last_checked timestamp with time zone,
    is_active boolean NOT NULL,
    notes text NOT NULL,
    CONSTRAINT public_seo_keyword_tracking_current_position_check CHECK ((current_position >= 0)),
    CONSTRAINT public_seo_keyword_tracking_search_volume_check CHECK ((search_volume >= 0))
);


--
-- Name: public_seo_keyword_tracking_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_keyword_tracking ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_keyword_tracking_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_pages (
    id bigint NOT NULL,
    page_type character varying(20) NOT NULL,
    url_path character varying(255) NOT NULL,
    title character varying(70) NOT NULL,
    meta_description character varying(160) NOT NULL,
    meta_keywords character varying(255) NOT NULL,
    canonical_url character varying(200),
    robots_meta character varying(100) NOT NULL,
    og_title character varying(95) NOT NULL,
    og_description character varying(200) NOT NULL,
    og_image character varying(100),
    og_type character varying(50) NOT NULL,
    twitter_card character varying(50) NOT NULL,
    twitter_title character varying(70) NOT NULL,
    twitter_description character varying(200) NOT NULL,
    twitter_image character varying(100),
    structured_data jsonb NOT NULL,
    focus_keyword character varying(100) NOT NULL,
    secondary_keywords text NOT NULL,
    is_active boolean NOT NULL,
    last_modified timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: public_seo_pages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_pages ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_pages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_ranking_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_ranking_history (
    id bigint NOT NULL,
    "position" integer NOT NULL,
    checked_at timestamp with time zone NOT NULL,
    keyword_tracking_id bigint NOT NULL,
    CONSTRAINT public_seo_ranking_history_position_check CHECK (("position" >= 0))
);


--
-- Name: public_seo_ranking_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_ranking_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_ranking_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_redirects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_redirects (
    id bigint NOT NULL,
    old_path character varying(255) NOT NULL,
    new_path character varying(255) NOT NULL,
    redirect_type integer NOT NULL,
    hit_count integer NOT NULL,
    last_accessed timestamp with time zone,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    notes text NOT NULL,
    CONSTRAINT public_seo_redirects_hit_count_check CHECK ((hit_count >= 0))
);


--
-- Name: public_seo_redirects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_redirects ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_redirects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_robots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_robots (
    id bigint NOT NULL,
    content text NOT NULL,
    is_active boolean NOT NULL,
    last_modified timestamp with time zone NOT NULL
);


--
-- Name: public_seo_robots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_robots ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_robots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_seo_sitemap; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_seo_sitemap (
    id bigint NOT NULL,
    url_path character varying(255) NOT NULL,
    priority double precision NOT NULL,
    change_frequency character varying(20) NOT NULL,
    last_modified timestamp with time zone NOT NULL,
    is_active boolean NOT NULL
);


--
-- Name: public_seo_sitemap_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_seo_sitemap ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_seo_sitemap_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_staff_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_staff_users (
    id bigint NOT NULL,
    username character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    password character varying(128) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    is_active boolean NOT NULL,
    is_staff boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_login timestamp with time zone,
    session_token character varying(64),
    token_expires_at timestamp with time zone
);


--
-- Name: public_staff_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_staff_users ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_staff_users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_subdomain_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_subdomain_reservations (
    id bigint NOT NULL,
    subdomain character varying(63) NOT NULL,
    reason character varying(20) NOT NULL,
    notes text NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: public_subdomain_reservations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_subdomain_reservations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_subdomain_reservations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_support_contact_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_support_contact_requests (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    email character varying(254) NOT NULL,
    phone character varying(20) NOT NULL,
    company character varying(255) NOT NULL,
    job_title character varying(100) NOT NULL,
    request_type character varying(20) NOT NULL,
    message text NOT NULL,
    company_size character varying(20) NOT NULL,
    is_processed boolean NOT NULL,
    processed_at timestamp with time zone,
    notes text NOT NULL,
    ip_address inet,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: public_support_contact_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_support_contact_requests ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_support_contact_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_support_faq; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_support_faq (
    id bigint NOT NULL,
    category character varying(20) NOT NULL,
    question character varying(255) NOT NULL,
    answer text NOT NULL,
    slug character varying(255) NOT NULL,
    meta_description character varying(160) NOT NULL,
    "order" integer NOT NULL,
    is_featured boolean NOT NULL,
    is_active boolean NOT NULL,
    view_count integer NOT NULL,
    helpful_count integer NOT NULL,
    not_helpful_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT public_support_faq_helpful_count_check CHECK ((helpful_count >= 0)),
    CONSTRAINT public_support_faq_not_helpful_count_check CHECK ((not_helpful_count >= 0)),
    CONSTRAINT public_support_faq_order_check CHECK (("order" >= 0)),
    CONSTRAINT public_support_faq_view_count_check CHECK ((view_count >= 0))
);


--
-- Name: public_support_faq_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_support_faq ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_support_faq_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_support_replies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_support_replies (
    id bigint NOT NULL,
    message text NOT NULL,
    is_internal_note boolean NOT NULL,
    sender_name character varying(100) NOT NULL,
    sender_email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    has_attachments boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    ticket_id uuid NOT NULL
);


--
-- Name: public_support_replies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_support_replies ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_support_replies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_support_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_support_tickets (
    ticket_id uuid NOT NULL,
    ticket_number character varying(20) NOT NULL,
    name character varying(100) NOT NULL,
    email character varying(254) NOT NULL,
    phone character varying(20) NOT NULL,
    company_name character varying(255) NOT NULL,
    category character varying(20) NOT NULL,
    subject character varying(255) NOT NULL,
    message text NOT NULL,
    status character varying(20) NOT NULL,
    priority character varying(20) NOT NULL,
    assigned_to_email character varying(254),
    ip_address inet,
    user_agent text NOT NULL,
    referrer character varying(500) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    first_response_at timestamp with time zone,
    resolved_at timestamp with time zone,
    closed_at timestamp with time zone,
    response_time_minutes integer,
    resolution_time_minutes integer,
    CONSTRAINT public_support_tickets_resolution_time_minutes_check CHECK ((resolution_time_minutes >= 0)),
    CONSTRAINT public_support_tickets_response_time_minutes_check CHECK ((response_time_minutes >= 0))
);


--
-- Name: public_tenant_approval_workflow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_tenant_approval_workflow (
    id bigint NOT NULL,
    reviewed_at timestamp with time zone,
    approval_notes text,
    signup_notification_sent boolean NOT NULL,
    signup_notification_sent_at timestamp with time zone,
    approval_notification_sent boolean NOT NULL,
    approval_notification_sent_at timestamp with time zone,
    generated_password character varying(255),
    login_url character varying(200),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    reviewed_by_id bigint,
    signup_request_id uuid NOT NULL
);


--
-- Name: public_tenant_approval_workflow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_tenant_approval_workflow ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_tenant_approval_workflow_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_tenant_notification_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_tenant_notification_log (
    id bigint NOT NULL,
    notification_type character varying(30) NOT NULL,
    recipient_email character varying(254) NOT NULL,
    subject character varying(255) NOT NULL,
    sent_successfully boolean NOT NULL,
    error_message text,
    sent_at timestamp with time zone NOT NULL,
    signup_request_id uuid NOT NULL
);


--
-- Name: public_tenant_notification_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_tenant_notification_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_tenant_notification_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_tenant_signup_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_tenant_signup_requests (
    request_id uuid NOT NULL,
    company_name character varying(255) NOT NULL,
    trading_name character varying(255) NOT NULL,
    subdomain character varying(63) NOT NULL,
    email character varying(254) NOT NULL,
    phone character varying(20) NOT NULL,
    country character varying(100) NOT NULL,
    first_name character varying(50) NOT NULL,
    last_name character varying(50) NOT NULL,
    admin_email character varying(254) NOT NULL,
    admin_phone character varying(20) NOT NULL,
    industry character varying(100) NOT NULL,
    business_type character varying(50) NOT NULL,
    estimated_users integer NOT NULL,
    selected_plan character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    tenant_created boolean NOT NULL,
    created_company_id character varying(10),
    created_schema_name character varying(63),
    error_message text,
    retry_count integer NOT NULL,
    ip_address inet,
    user_agent text NOT NULL,
    referral_source character varying(100) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT public_tenant_signup_requests_estimated_users_check CHECK ((estimated_users >= 0)),
    CONSTRAINT public_tenant_signup_requests_retry_count_check CHECK ((retry_count >= 0))
);


--
-- Name: public_user_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_user_activities (
    id bigint NOT NULL,
    action character varying(20) NOT NULL,
    app_name character varying(50) NOT NULL,
    model_name character varying(50) NOT NULL,
    object_id character varying(100) NOT NULL,
    description text NOT NULL,
    ip_address inet,
    user_agent text NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: public_user_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_user_activities ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_user_activities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: public_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.public_users (
    id bigint NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    identifier character varying(50) NOT NULL,
    email character varying(254) NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(50) NOT NULL,
    last_name character varying(50) NOT NULL,
    phone character varying(20) NOT NULL,
    role character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    is_staff boolean NOT NULL,
    is_superuser boolean NOT NULL,
    is_admin boolean NOT NULL,
    email_verified boolean NOT NULL,
    email_verification_token character varying(100),
    password_changed_at timestamp with time zone NOT NULL,
    force_password_change boolean NOT NULL,
    failed_login_attempts integer NOT NULL,
    locked_until timestamp with time zone,
    last_login_ip inet,
    avatar character varying(100),
    bio text NOT NULL,
    can_manage_seo boolean NOT NULL,
    can_manage_blog boolean NOT NULL,
    can_manage_support boolean NOT NULL,
    can_manage_companies boolean NOT NULL,
    can_view_analytics boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    last_activity timestamp with time zone,
    CONSTRAINT public_users_failed_login_attempts_check CHECK ((failed_login_attempts >= 0))
);


--
-- Name: public_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.public_users ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.public_users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tenant_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_domains (
    id bigint NOT NULL,
    domain character varying(253) NOT NULL,
    is_primary boolean NOT NULL,
    ssl_enabled boolean NOT NULL,
    redirect_to_primary boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    tenant_id character varying(10) NOT NULL
);


--
-- Name: tenant_domains_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.tenant_domains ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.tenant_domains_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tenant_email_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_email_settings (
    id bigint NOT NULL,
    smtp_host character varying(255) NOT NULL,
    smtp_port integer NOT NULL,
    smtp_username character varying(255) NOT NULL,
    smtp_password character varying(255) NOT NULL,
    use_tls boolean NOT NULL,
    use_ssl boolean NOT NULL,
    from_email character varying(254) NOT NULL,
    from_name character varying(255) NOT NULL,
    reply_to_email character varying(254),
    timeout integer NOT NULL,
    is_active boolean NOT NULL,
    is_verified boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_tested_at timestamp with time zone,
    test_result text NOT NULL,
    company_id character varying(10) NOT NULL
);


--
-- Name: tenant_email_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.tenant_email_settings ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.tenant_email_settings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tenant_invoice_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_invoice_settings (
    id bigint NOT NULL,
    invoice_prefix character varying(10) NOT NULL,
    invoice_number_start integer NOT NULL,
    invoice_number_padding integer NOT NULL,
    default_payment_terms_days integer NOT NULL,
    invoice_notes text NOT NULL,
    invoice_terms text NOT NULL,
    show_company_logo boolean NOT NULL,
    invoice_template character varying(50) NOT NULL,
    default_tax_rate numeric(5,2) NOT NULL,
    tax_name character varying(50) NOT NULL,
    send_invoice_email boolean NOT NULL,
    invoice_email_subject character varying(255) NOT NULL,
    invoice_email_body text NOT NULL,
    enable_efris boolean NOT NULL,
    efris_tin character varying(50) NOT NULL,
    efris_device_no character varying(50) NOT NULL,
    efris_private_key text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    company_id character varying(10) NOT NULL
);


--
-- Name: tenant_invoice_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.tenant_invoice_settings ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.tenant_invoice_settings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_company company_company_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_company
    ADD CONSTRAINT company_company_pkey PRIMARY KEY (company_id);


--
-- Name: company_company company_company_schema_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_company
    ADD CONSTRAINT company_company_schema_name_key UNIQUE (schema_name);


--
-- Name: company_company company_company_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_company
    ADD CONSTRAINT company_company_slug_key UNIQUE (slug);


--
-- Name: company_companyrelationship company_companyrelations_company_id_related_compa_b84ef8a0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_companyrelationship
    ADD CONSTRAINT company_companyrelations_company_id_related_compa_b84ef8a0_uniq UNIQUE (company_id, related_company_id, relationship_type);


--
-- Name: company_companyrelationship company_companyrelationship_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_companyrelationship
    ADD CONSTRAINT company_companyrelationship_pkey PRIMARY KEY (id);


--
-- Name: company_crosscompanytransaction company_crosscompanytransaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_crosscompanytransaction
    ADD CONSTRAINT company_crosscompanytransaction_pkey PRIMARY KEY (id);


--
-- Name: company_crosscompanytransaction company_crosscompanytransaction_transaction_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_crosscompanytransaction
    ADD CONSTRAINT company_crosscompanytransaction_transaction_number_key UNIQUE (transaction_number);


--
-- Name: company_efriscommoditycategory company_efriscommoditycategory_commodity_category_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_efriscommoditycategory
    ADD CONSTRAINT company_efriscommoditycategory_commodity_category_code_key UNIQUE (commodity_category_code);


--
-- Name: company_efriscommoditycategory company_efriscommoditycategory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_efriscommoditycategory
    ADD CONSTRAINT company_efriscommoditycategory_pkey PRIMARY KEY (id);


--
-- Name: company_efrishscode company_efrishscode_hs_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_efrishscode
    ADD CONSTRAINT company_efrishscode_hs_code_key UNIQUE (hs_code);


--
-- Name: company_efrishscode company_efrishscode_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_efrishscode
    ADD CONSTRAINT company_efrishscode_pkey PRIMARY KEY (id);


--
-- Name: company_subscriptionplan company_subscriptionplan_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_subscriptionplan
    ADD CONSTRAINT company_subscriptionplan_name_key UNIQUE (name);


--
-- Name: company_subscriptionplan company_subscriptionplan_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_subscriptionplan
    ADD CONSTRAINT company_subscriptionplan_pkey PRIMARY KEY (id);


--
-- Name: django_celery_beat_clockedschedule django_celery_beat_clockedschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_clockedschedule
    ADD CONSTRAINT django_celery_beat_clockedschedule_pkey PRIMARY KEY (id);


--
-- Name: django_celery_beat_crontabschedule django_celery_beat_crontabschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_crontabschedule
    ADD CONSTRAINT django_celery_beat_crontabschedule_pkey PRIMARY KEY (id);


--
-- Name: django_celery_beat_intervalschedule django_celery_beat_intervalschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_intervalschedule
    ADD CONSTRAINT django_celery_beat_intervalschedule_pkey PRIMARY KEY (id);


--
-- Name: django_celery_beat_periodictask django_celery_beat_periodictask_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_periodictask_name_key UNIQUE (name);


--
-- Name: django_celery_beat_periodictask django_celery_beat_periodictask_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_periodictask_pkey PRIMARY KEY (id);


--
-- Name: django_celery_beat_periodictasks django_celery_beat_periodictasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictasks
    ADD CONSTRAINT django_celery_beat_periodictasks_pkey PRIMARY KEY (ident);


--
-- Name: django_celery_beat_solarschedule django_celery_beat_solar_event_latitude_longitude_ba64999a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_solarschedule
    ADD CONSTRAINT django_celery_beat_solar_event_latitude_longitude_ba64999a_uniq UNIQUE (event, latitude, longitude);


--
-- Name: django_celery_beat_solarschedule django_celery_beat_solarschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_solarschedule
    ADD CONSTRAINT django_celery_beat_solarschedule_pkey PRIMARY KEY (id);


--
-- Name: django_celery_results_chordcounter django_celery_results_chordcounter_group_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_chordcounter
    ADD CONSTRAINT django_celery_results_chordcounter_group_id_key UNIQUE (group_id);


--
-- Name: django_celery_results_chordcounter django_celery_results_chordcounter_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_chordcounter
    ADD CONSTRAINT django_celery_results_chordcounter_pkey PRIMARY KEY (id);


--
-- Name: django_celery_results_groupresult django_celery_results_groupresult_group_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_groupresult
    ADD CONSTRAINT django_celery_results_groupresult_group_id_key UNIQUE (group_id);


--
-- Name: django_celery_results_groupresult django_celery_results_groupresult_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_groupresult
    ADD CONSTRAINT django_celery_results_groupresult_pkey PRIMARY KEY (id);


--
-- Name: django_celery_results_taskresult django_celery_results_taskresult_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_taskresult
    ADD CONSTRAINT django_celery_results_taskresult_pkey PRIMARY KEY (id);


--
-- Name: django_celery_results_taskresult django_celery_results_taskresult_task_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_results_taskresult
    ADD CONSTRAINT django_celery_results_taskresult_task_id_key UNIQUE (task_id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: primebooks_appversion primebooks_appversion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_appversion
    ADD CONSTRAINT primebooks_appversion_pkey PRIMARY KEY (id);


--
-- Name: primebooks_appversion primebooks_appversion_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_appversion
    ADD CONSTRAINT primebooks_appversion_version_key UNIQUE (version);


--
-- Name: primebooks_appversions primebooks_appversions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_appversions
    ADD CONSTRAINT primebooks_appversions_pkey PRIMARY KEY (id);


--
-- Name: primebooks_appversions primebooks_appversions_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_appversions
    ADD CONSTRAINT primebooks_appversions_version_key UNIQUE (version);


--
-- Name: primebooks_errorreport primebooks_errorreport_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_errorreport
    ADD CONSTRAINT primebooks_errorreport_pkey PRIMARY KEY (id);


--
-- Name: primebooks_maintenancewindow primebooks_maintenancewindow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_maintenancewindow
    ADD CONSTRAINT primebooks_maintenancewindow_pkey PRIMARY KEY (id);


--
-- Name: primebooks_updatelog primebooks_updatelog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_updatelog
    ADD CONSTRAINT primebooks_updatelog_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_conversions public_analytics_conversions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_conversions
    ADD CONSTRAINT public_analytics_conversions_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_daily_stats public_analytics_daily_stats_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_daily_stats
    ADD CONSTRAINT public_analytics_daily_stats_date_key UNIQUE (date);


--
-- Name: public_analytics_daily_stats public_analytics_daily_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_daily_stats
    ADD CONSTRAINT public_analytics_daily_stats_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_events public_analytics_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_events
    ADD CONSTRAINT public_analytics_events_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_pageviews public_analytics_pageviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_pageviews
    ADD CONSTRAINT public_analytics_pageviews_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_sessions public_analytics_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_sessions
    ADD CONSTRAINT public_analytics_sessions_pkey PRIMARY KEY (id);


--
-- Name: public_analytics_sessions public_analytics_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_analytics_sessions
    ADD CONSTRAINT public_analytics_sessions_session_id_key UNIQUE (session_id);


--
-- Name: public_blog_categories public_blog_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_categories
    ADD CONSTRAINT public_blog_categories_name_key UNIQUE (name);


--
-- Name: public_blog_categories public_blog_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_categories
    ADD CONSTRAINT public_blog_categories_pkey PRIMARY KEY (id);


--
-- Name: public_blog_categories public_blog_categories_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_categories
    ADD CONSTRAINT public_blog_categories_slug_key UNIQUE (slug);


--
-- Name: public_blog_comments public_blog_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_comments
    ADD CONSTRAINT public_blog_comments_pkey PRIMARY KEY (id);


--
-- Name: public_blog_newsletter public_blog_newsletter_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_newsletter
    ADD CONSTRAINT public_blog_newsletter_email_key UNIQUE (email);


--
-- Name: public_blog_newsletter public_blog_newsletter_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_newsletter
    ADD CONSTRAINT public_blog_newsletter_pkey PRIMARY KEY (id);


--
-- Name: public_blog_newsletter public_blog_newsletter_unsubscribe_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_newsletter
    ADD CONSTRAINT public_blog_newsletter_unsubscribe_token_key UNIQUE (unsubscribe_token);


--
-- Name: public_blog_posts public_blog_posts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_posts
    ADD CONSTRAINT public_blog_posts_pkey PRIMARY KEY (id);


--
-- Name: public_blog_posts public_blog_posts_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_posts
    ADD CONSTRAINT public_blog_posts_slug_key UNIQUE (slug);


--
-- Name: public_newsletter_subscribers public_newsletter_subscribers_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_newsletter_subscribers
    ADD CONSTRAINT public_newsletter_subscribers_email_key UNIQUE (email);


--
-- Name: public_newsletter_subscribers public_newsletter_subscribers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_newsletter_subscribers
    ADD CONSTRAINT public_newsletter_subscribers_pkey PRIMARY KEY (id);


--
-- Name: public_password_reset_tokens public_password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_password_reset_tokens
    ADD CONSTRAINT public_password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: public_password_reset_tokens public_password_reset_tokens_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_password_reset_tokens
    ADD CONSTRAINT public_password_reset_tokens_token_key UNIQUE (token);


--
-- Name: public_seo_audits public_seo_audits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_audits
    ADD CONSTRAINT public_seo_audits_pkey PRIMARY KEY (id);


--
-- Name: public_seo_keyword_tracking public_seo_keyword_tracking_keyword_target_url_4c87e2a8_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_keyword_tracking
    ADD CONSTRAINT public_seo_keyword_tracking_keyword_target_url_4c87e2a8_uniq UNIQUE (keyword, target_url);


--
-- Name: public_seo_keyword_tracking public_seo_keyword_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_keyword_tracking
    ADD CONSTRAINT public_seo_keyword_tracking_pkey PRIMARY KEY (id);


--
-- Name: public_seo_pages public_seo_pages_page_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_pages
    ADD CONSTRAINT public_seo_pages_page_type_key UNIQUE (page_type);


--
-- Name: public_seo_pages public_seo_pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_pages
    ADD CONSTRAINT public_seo_pages_pkey PRIMARY KEY (id);


--
-- Name: public_seo_pages public_seo_pages_url_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_pages
    ADD CONSTRAINT public_seo_pages_url_path_key UNIQUE (url_path);


--
-- Name: public_seo_ranking_history public_seo_ranking_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_ranking_history
    ADD CONSTRAINT public_seo_ranking_history_pkey PRIMARY KEY (id);


--
-- Name: public_seo_redirects public_seo_redirects_old_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_redirects
    ADD CONSTRAINT public_seo_redirects_old_path_key UNIQUE (old_path);


--
-- Name: public_seo_redirects public_seo_redirects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_redirects
    ADD CONSTRAINT public_seo_redirects_pkey PRIMARY KEY (id);


--
-- Name: public_seo_robots public_seo_robots_is_active_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_robots
    ADD CONSTRAINT public_seo_robots_is_active_key UNIQUE (is_active);


--
-- Name: public_seo_robots public_seo_robots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_robots
    ADD CONSTRAINT public_seo_robots_pkey PRIMARY KEY (id);


--
-- Name: public_seo_sitemap public_seo_sitemap_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_sitemap
    ADD CONSTRAINT public_seo_sitemap_pkey PRIMARY KEY (id);


--
-- Name: public_seo_sitemap public_seo_sitemap_url_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_sitemap
    ADD CONSTRAINT public_seo_sitemap_url_path_key UNIQUE (url_path);


--
-- Name: public_staff_users public_staff_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_staff_users
    ADD CONSTRAINT public_staff_users_email_key UNIQUE (email);


--
-- Name: public_staff_users public_staff_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_staff_users
    ADD CONSTRAINT public_staff_users_pkey PRIMARY KEY (id);


--
-- Name: public_staff_users public_staff_users_session_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_staff_users
    ADD CONSTRAINT public_staff_users_session_token_key UNIQUE (session_token);


--
-- Name: public_staff_users public_staff_users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_staff_users
    ADD CONSTRAINT public_staff_users_username_key UNIQUE (username);


--
-- Name: public_subdomain_reservations public_subdomain_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_subdomain_reservations
    ADD CONSTRAINT public_subdomain_reservations_pkey PRIMARY KEY (id);


--
-- Name: public_subdomain_reservations public_subdomain_reservations_subdomain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_subdomain_reservations
    ADD CONSTRAINT public_subdomain_reservations_subdomain_key UNIQUE (subdomain);


--
-- Name: public_support_contact_requests public_support_contact_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_contact_requests
    ADD CONSTRAINT public_support_contact_requests_pkey PRIMARY KEY (id);


--
-- Name: public_support_faq public_support_faq_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_faq
    ADD CONSTRAINT public_support_faq_pkey PRIMARY KEY (id);


--
-- Name: public_support_faq public_support_faq_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_faq
    ADD CONSTRAINT public_support_faq_slug_key UNIQUE (slug);


--
-- Name: public_support_replies public_support_replies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_replies
    ADD CONSTRAINT public_support_replies_pkey PRIMARY KEY (id);


--
-- Name: public_support_tickets public_support_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_tickets
    ADD CONSTRAINT public_support_tickets_pkey PRIMARY KEY (ticket_id);


--
-- Name: public_support_tickets public_support_tickets_ticket_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_tickets
    ADD CONSTRAINT public_support_tickets_ticket_number_key UNIQUE (ticket_number);


--
-- Name: public_tenant_approval_workflow public_tenant_approval_workflow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_approval_workflow
    ADD CONSTRAINT public_tenant_approval_workflow_pkey PRIMARY KEY (id);


--
-- Name: public_tenant_approval_workflow public_tenant_approval_workflow_signup_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_approval_workflow
    ADD CONSTRAINT public_tenant_approval_workflow_signup_request_id_key UNIQUE (signup_request_id);


--
-- Name: public_tenant_notification_log public_tenant_notification_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_notification_log
    ADD CONSTRAINT public_tenant_notification_log_pkey PRIMARY KEY (id);


--
-- Name: public_tenant_signup_requests public_tenant_signup_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_signup_requests
    ADD CONSTRAINT public_tenant_signup_requests_pkey PRIMARY KEY (request_id);


--
-- Name: public_tenant_signup_requests public_tenant_signup_requests_subdomain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_signup_requests
    ADD CONSTRAINT public_tenant_signup_requests_subdomain_key UNIQUE (subdomain);


--
-- Name: public_user_activities public_user_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_user_activities
    ADD CONSTRAINT public_user_activities_pkey PRIMARY KEY (id);


--
-- Name: public_users public_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_users
    ADD CONSTRAINT public_users_email_key UNIQUE (email);


--
-- Name: public_users public_users_identifier_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_users
    ADD CONSTRAINT public_users_identifier_key UNIQUE (identifier);


--
-- Name: public_users public_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_users
    ADD CONSTRAINT public_users_pkey PRIMARY KEY (id);


--
-- Name: public_users public_users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_users
    ADD CONSTRAINT public_users_username_key UNIQUE (username);


--
-- Name: tenant_domains tenant_domains_domain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_domain_key UNIQUE (domain);


--
-- Name: tenant_domains tenant_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_pkey PRIMARY KEY (id);


--
-- Name: tenant_email_settings tenant_email_settings_company_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_email_settings
    ADD CONSTRAINT tenant_email_settings_company_id_key UNIQUE (company_id);


--
-- Name: tenant_email_settings tenant_email_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_email_settings
    ADD CONSTRAINT tenant_email_settings_pkey PRIMARY KEY (id);


--
-- Name: tenant_invoice_settings tenant_invoice_settings_company_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invoice_settings
    ADD CONSTRAINT tenant_invoice_settings_company_id_key UNIQUE (company_id);


--
-- Name: tenant_invoice_settings tenant_invoice_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invoice_settings
    ADD CONSTRAINT tenant_invoice_settings_pkey PRIMARY KEY (id);


--
-- Name: company_com_efris_e_da20b9_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_efris_e_da20b9_idx ON public.company_company USING btree (efris_enabled);


--
-- Name: company_com_efris_i_aeac99_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_efris_i_aeac99_idx ON public.company_company USING btree (efris_is_active);


--
-- Name: company_com_efris_l_3e161a_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_efris_l_3e161a_idx ON public.company_company USING btree (efris_last_sync);


--
-- Name: company_com_last_ac_0754c4_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_last_ac_0754c4_idx ON public.company_company USING btree (last_activity_at);


--
-- Name: company_com_status_c491e8_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_status_c491e8_idx ON public.company_company USING btree (status);


--
-- Name: company_com_subscri_f24aad_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_subscri_f24aad_idx ON public.company_company USING btree (subscription_ends_at);


--
-- Name: company_com_trial_e_2695c2_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_com_trial_e_2695c2_idx ON public.company_company USING btree (trial_ends_at);


--
-- Name: company_company_company_id_4ed2ca46_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_company_company_id_4ed2ca46_like ON public.company_company USING btree (company_id varchar_pattern_ops);


--
-- Name: company_company_plan_id_2c0e5a90; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_company_plan_id_2c0e5a90 ON public.company_company USING btree (plan_id);


--
-- Name: company_company_schema_name_b34e24f8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_company_schema_name_b34e24f8_like ON public.company_company USING btree (schema_name varchar_pattern_ops);


--
-- Name: company_company_slug_cefb92db_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_company_slug_cefb92db_like ON public.company_company USING btree (slug varchar_pattern_ops);


--
-- Name: company_companyrelationship_company_id_9af6d45a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_companyrelationship_company_id_9af6d45a ON public.company_companyrelationship USING btree (company_id);


--
-- Name: company_companyrelationship_company_id_9af6d45a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_companyrelationship_company_id_9af6d45a_like ON public.company_companyrelationship USING btree (company_id varchar_pattern_ops);


--
-- Name: company_companyrelationship_related_company_id_cf18739d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_companyrelationship_related_company_id_cf18739d ON public.company_companyrelationship USING btree (related_company_id);


--
-- Name: company_companyrelationship_related_company_id_cf18739d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_companyrelationship_related_company_id_cf18739d_like ON public.company_companyrelationship USING btree (related_company_id varchar_pattern_ops);


--
-- Name: company_crosscompanytran_destination_company_id_54932cef_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_crosscompanytran_destination_company_id_54932cef_like ON public.company_crosscompanytransaction USING btree (destination_company_id varchar_pattern_ops);


--
-- Name: company_crosscompanytran_transaction_number_0c4d96ae_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_crosscompanytran_transaction_number_0c4d96ae_like ON public.company_crosscompanytransaction USING btree (transaction_number varchar_pattern_ops);


--
-- Name: company_crosscompanytransaction_destination_company_id_54932cef; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_crosscompanytransaction_destination_company_id_54932cef ON public.company_crosscompanytransaction USING btree (destination_company_id);


--
-- Name: company_crosscompanytransaction_source_company_id_780155ca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_crosscompanytransaction_source_company_id_780155ca ON public.company_crosscompanytransaction USING btree (source_company_id);


--
-- Name: company_crosscompanytransaction_source_company_id_780155ca_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_crosscompanytransaction_source_company_id_780155ca_like ON public.company_crosscompanytransaction USING btree (source_company_id varchar_pattern_ops);


--
-- Name: company_efr_commodi_3ab183_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efr_commodi_3ab183_idx ON public.company_efriscommoditycategory USING btree (commodity_category_code);


--
-- Name: company_efr_commodi_53d7a9_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efr_commodi_53d7a9_idx ON public.company_efriscommoditycategory USING btree (commodity_category_name);


--
-- Name: company_efr_parent__2dbe28_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efr_parent__2dbe28_idx ON public.company_efriscommoditycategory USING btree (parent_code, enable_status_code);


--
-- Name: company_efr_service_962966_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efr_service_962966_idx ON public.company_efriscommoditycategory USING btree (service_mark, enable_status_code, is_leaf_node);


--
-- Name: company_efriscommodityca_commodity_category_code_9d3b5fe6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efriscommodityca_commodity_category_code_9d3b5fe6_like ON public.company_efriscommoditycategory USING btree (commodity_category_code varchar_pattern_ops);


--
-- Name: company_efrishscode_hs_code_f8df25bc_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efrishscode_hs_code_f8df25bc_like ON public.company_efrishscode USING btree (hs_code varchar_pattern_ops);


--
-- Name: company_efrishscode_parent_code_3c9acc1c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efrishscode_parent_code_3c9acc1c ON public.company_efrishscode USING btree (parent_code);


--
-- Name: company_efrishscode_parent_code_3c9acc1c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_efrishscode_parent_code_3c9acc1c_like ON public.company_efrishscode USING btree (parent_code varchar_pattern_ops);


--
-- Name: company_subscriptionplan_name_82552ca7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_subscriptionplan_name_82552ca7_like ON public.company_subscriptionplan USING btree (name varchar_pattern_ops);


--
-- Name: django_cele_date_cr_bd6c1d_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_date_cr_bd6c1d_idx ON public.django_celery_results_groupresult USING btree (date_created);


--
-- Name: django_cele_date_cr_f04a50_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_date_cr_f04a50_idx ON public.django_celery_results_taskresult USING btree (date_created);


--
-- Name: django_cele_date_do_caae0e_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_date_do_caae0e_idx ON public.django_celery_results_groupresult USING btree (date_done);


--
-- Name: django_cele_date_do_f59aad_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_date_do_f59aad_idx ON public.django_celery_results_taskresult USING btree (date_done);


--
-- Name: django_cele_status_9b6201_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_status_9b6201_idx ON public.django_celery_results_taskresult USING btree (status);


--
-- Name: django_cele_task_na_08aec9_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_task_na_08aec9_idx ON public.django_celery_results_taskresult USING btree (task_name);


--
-- Name: django_cele_worker_d54dd8_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_cele_worker_d54dd8_idx ON public.django_celery_results_taskresult USING btree (worker);


--
-- Name: django_celery_beat_periodictask_clocked_id_47a69f82; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_beat_periodictask_clocked_id_47a69f82 ON public.django_celery_beat_periodictask USING btree (clocked_id);


--
-- Name: django_celery_beat_periodictask_crontab_id_d3cba168; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_beat_periodictask_crontab_id_d3cba168 ON public.django_celery_beat_periodictask USING btree (crontab_id);


--
-- Name: django_celery_beat_periodictask_interval_id_a8ca27da; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_beat_periodictask_interval_id_a8ca27da ON public.django_celery_beat_periodictask USING btree (interval_id);


--
-- Name: django_celery_beat_periodictask_name_265a36b7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_beat_periodictask_name_265a36b7_like ON public.django_celery_beat_periodictask USING btree (name varchar_pattern_ops);


--
-- Name: django_celery_beat_periodictask_solar_id_a87ce72c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_beat_periodictask_solar_id_a87ce72c ON public.django_celery_beat_periodictask USING btree (solar_id);


--
-- Name: django_celery_results_chordcounter_group_id_1f70858c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_results_chordcounter_group_id_1f70858c_like ON public.django_celery_results_chordcounter USING btree (group_id varchar_pattern_ops);


--
-- Name: django_celery_results_groupresult_group_id_a085f1a9_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_results_groupresult_group_id_a085f1a9_like ON public.django_celery_results_groupresult USING btree (group_id varchar_pattern_ops);


--
-- Name: django_celery_results_taskresult_task_id_de0d95bf_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_celery_results_taskresult_task_id_de0d95bf_like ON public.django_celery_results_taskresult USING btree (task_id varchar_pattern_ops);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: primebooks_appversion_rollback_target_id_aad417f8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_appversion_rollback_target_id_aad417f8 ON public.primebooks_appversion USING btree (rollback_target_id);


--
-- Name: primebooks_appversion_version_71c4d2db_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_appversion_version_71c4d2db_like ON public.primebooks_appversion USING btree (version varchar_pattern_ops);


--
-- Name: primebooks_appversions_version_c2444891_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_appversions_version_c2444891_like ON public.primebooks_appversions USING btree (version varchar_pattern_ops);


--
-- Name: primebooks_errorreport_app_version_id_78838568; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_errorreport_app_version_id_78838568 ON public.primebooks_errorreport USING btree (app_version_id);


--
-- Name: primebooks_maintenancewindow_version_id_92901ac5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_maintenancewindow_version_id_92901ac5 ON public.primebooks_maintenancewindow USING btree (version_id);


--
-- Name: primebooks_updatelog_version_id_7364cf6f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX primebooks_updatelog_version_id_7364cf6f ON public.primebooks_updatelog USING btree (version_id);


--
-- Name: public_anal_action_e78260_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_action_e78260_idx ON public.public_analytics_events USING btree (action, occurred_at);


--
-- Name: public_anal_categor_1e5f66_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_categor_1e5f66_idx ON public.public_analytics_events USING btree (category, occurred_at);


--
-- Name: public_anal_convers_25c958_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_convers_25c958_idx ON public.public_analytics_conversions USING btree (conversion_type, converted_at);


--
-- Name: public_anal_convert_95ff02_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_convert_95ff02_idx ON public.public_analytics_sessions USING btree (converted, started_at);


--
-- Name: public_anal_session_782218_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_session_782218_idx ON public.public_analytics_pageviews USING btree (session_id, viewed_at);


--
-- Name: public_anal_session_9a8914_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_session_9a8914_idx ON public.public_analytics_events USING btree (session_id, occurred_at);


--
-- Name: public_anal_url_pat_253726_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_url_pat_253726_idx ON public.public_analytics_pageviews USING btree (url_path, viewed_at);


--
-- Name: public_anal_utm_cam_0f7363_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_utm_cam_0f7363_idx ON public.public_analytics_pageviews USING btree (utm_campaign, viewed_at);


--
-- Name: public_anal_utm_cam_94c67c_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_utm_cam_94c67c_idx ON public.public_analytics_conversions USING btree (utm_campaign, converted_at);


--
-- Name: public_anal_visitor_555612_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_visitor_555612_idx ON public.public_analytics_sessions USING btree (visitor_id, started_at);


--
-- Name: public_anal_visitor_6266ef_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_visitor_6266ef_idx ON public.public_analytics_pageviews USING btree (visitor_id, viewed_at);


--
-- Name: public_anal_visitor_b9a160_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_anal_visitor_b9a160_idx ON public.public_analytics_conversions USING btree (visitor_id, converted_at);


--
-- Name: public_analytics_conversions_converted_at_36c50fec; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_conversions_converted_at_36c50fec ON public.public_analytics_conversions USING btree (converted_at);


--
-- Name: public_analytics_conversions_visitor_id_cee742e4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_conversions_visitor_id_cee742e4 ON public.public_analytics_conversions USING btree (visitor_id);


--
-- Name: public_analytics_conversions_visitor_id_cee742e4_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_conversions_visitor_id_cee742e4_like ON public.public_analytics_conversions USING btree (visitor_id varchar_pattern_ops);


--
-- Name: public_analytics_events_occurred_at_b85660c5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_events_occurred_at_b85660c5 ON public.public_analytics_events USING btree (occurred_at);


--
-- Name: public_analytics_events_session_id_b009fb90; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_events_session_id_b009fb90 ON public.public_analytics_events USING btree (session_id);


--
-- Name: public_analytics_events_session_id_b009fb90_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_events_session_id_b009fb90_like ON public.public_analytics_events USING btree (session_id varchar_pattern_ops);


--
-- Name: public_analytics_events_visitor_id_3654a7ea; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_events_visitor_id_3654a7ea ON public.public_analytics_events USING btree (visitor_id);


--
-- Name: public_analytics_events_visitor_id_3654a7ea_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_events_visitor_id_3654a7ea_like ON public.public_analytics_events USING btree (visitor_id varchar_pattern_ops);


--
-- Name: public_analytics_pageviews_session_id_af2b1c8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_pageviews_session_id_af2b1c8b ON public.public_analytics_pageviews USING btree (session_id);


--
-- Name: public_analytics_pageviews_session_id_af2b1c8b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_pageviews_session_id_af2b1c8b_like ON public.public_analytics_pageviews USING btree (session_id varchar_pattern_ops);


--
-- Name: public_analytics_pageviews_viewed_at_03c113a1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_pageviews_viewed_at_03c113a1 ON public.public_analytics_pageviews USING btree (viewed_at);


--
-- Name: public_analytics_pageviews_visitor_id_8f1581d4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_pageviews_visitor_id_8f1581d4 ON public.public_analytics_pageviews USING btree (visitor_id);


--
-- Name: public_analytics_pageviews_visitor_id_8f1581d4_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_pageviews_visitor_id_8f1581d4_like ON public.public_analytics_pageviews USING btree (visitor_id varchar_pattern_ops);


--
-- Name: public_analytics_sessions_session_id_59d629c6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_sessions_session_id_59d629c6_like ON public.public_analytics_sessions USING btree (session_id varchar_pattern_ops);


--
-- Name: public_analytics_sessions_visitor_id_29f21aa3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_sessions_visitor_id_29f21aa3 ON public.public_analytics_sessions USING btree (visitor_id);


--
-- Name: public_analytics_sessions_visitor_id_29f21aa3_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_analytics_sessions_visitor_id_29f21aa3_like ON public.public_analytics_sessions USING btree (visitor_id varchar_pattern_ops);


--
-- Name: public_blog_categor_4918a4_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_categor_4918a4_idx ON public.public_blog_posts USING btree (category_id, status);


--
-- Name: public_blog_categories_name_f771648b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_categories_name_f771648b_like ON public.public_blog_categories USING btree (name varchar_pattern_ops);


--
-- Name: public_blog_categories_slug_911b6539_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_categories_slug_911b6539_like ON public.public_blog_categories USING btree (slug varchar_pattern_ops);


--
-- Name: public_blog_comments_post_id_a93f78ae; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_comments_post_id_a93f78ae ON public.public_blog_comments USING btree (post_id);


--
-- Name: public_blog_email_cbb42a_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_email_cbb42a_idx ON public.public_blog_comments USING btree (email);


--
-- Name: public_blog_newsletter_email_aa5d3fc7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_newsletter_email_aa5d3fc7_like ON public.public_blog_newsletter USING btree (email varchar_pattern_ops);


--
-- Name: public_blog_newsletter_unsubscribe_token_22c0f928_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_newsletter_unsubscribe_token_22c0f928_like ON public.public_blog_newsletter USING btree (unsubscribe_token varchar_pattern_ops);


--
-- Name: public_blog_post_id_bc5715_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_post_id_bc5715_idx ON public.public_blog_comments USING btree (post_id, is_approved);


--
-- Name: public_blog_posts_category_id_f060c64b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_posts_category_id_f060c64b ON public.public_blog_posts USING btree (category_id);


--
-- Name: public_blog_posts_slug_f814922d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_posts_slug_f814922d_like ON public.public_blog_posts USING btree (slug varchar_pattern_ops);


--
-- Name: public_blog_slug_e18e60_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_slug_e18e60_idx ON public.public_blog_posts USING btree (slug);


--
-- Name: public_blog_status_f3c34d_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_blog_status_f3c34d_idx ON public.public_blog_posts USING btree (status, published_at);


--
-- Name: public_newsletter_subscribers_email_bf336734_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_newsletter_subscribers_email_bf336734_like ON public.public_newsletter_subscribers USING btree (email varchar_pattern_ops);


--
-- Name: public_password_reset_tokens_token_0deedccb_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_password_reset_tokens_token_0deedccb_like ON public.public_password_reset_tokens USING btree (token varchar_pattern_ops);


--
-- Name: public_password_reset_tokens_user_id_4aeb9d7d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_password_reset_tokens_user_id_4aeb9d7d ON public.public_password_reset_tokens USING btree (user_id);


--
-- Name: public_seo_audits_page_id_2991d684; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_audits_page_id_2991d684 ON public.public_seo_audits USING btree (page_id);


--
-- Name: public_seo_pages_page_type_27dcd7ba_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_pages_page_type_27dcd7ba_like ON public.public_seo_pages USING btree (page_type varchar_pattern_ops);


--
-- Name: public_seo_pages_url_path_58f6ad4d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_pages_url_path_58f6ad4d_like ON public.public_seo_pages USING btree (url_path varchar_pattern_ops);


--
-- Name: public_seo_ranking_history_keyword_tracking_id_250ed7e6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_ranking_history_keyword_tracking_id_250ed7e6 ON public.public_seo_ranking_history USING btree (keyword_tracking_id);


--
-- Name: public_seo_redirects_old_path_9fae0416_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_redirects_old_path_9fae0416_like ON public.public_seo_redirects USING btree (old_path varchar_pattern_ops);


--
-- Name: public_seo_sitemap_url_path_ff0f6172_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_seo_sitemap_url_path_ff0f6172_like ON public.public_seo_sitemap USING btree (url_path varchar_pattern_ops);


--
-- Name: public_staff_users_email_b1f38794_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_staff_users_email_b1f38794_like ON public.public_staff_users USING btree (email varchar_pattern_ops);


--
-- Name: public_staff_users_session_token_449764fa_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_staff_users_session_token_449764fa_like ON public.public_staff_users USING btree (session_token varchar_pattern_ops);


--
-- Name: public_staff_users_username_5d6dd6c9_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_staff_users_username_5d6dd6c9_like ON public.public_staff_users USING btree (username varchar_pattern_ops);


--
-- Name: public_subdomain_reservations_subdomain_cbac9159_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_subdomain_reservations_subdomain_cbac9159_like ON public.public_subdomain_reservations USING btree (subdomain varchar_pattern_ops);


--
-- Name: public_supp_email_d3e6ce_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_supp_email_d3e6ce_idx ON public.public_support_tickets USING btree (email);


--
-- Name: public_supp_status_48b249_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_supp_status_48b249_idx ON public.public_support_tickets USING btree (status, created_at);


--
-- Name: public_supp_ticket__ca9fbb_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_supp_ticket__ca9fbb_idx ON public.public_support_tickets USING btree (ticket_number);


--
-- Name: public_support_faq_slug_9f79dc19_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_support_faq_slug_9f79dc19_like ON public.public_support_faq USING btree (slug varchar_pattern_ops);


--
-- Name: public_support_replies_ticket_id_0bc90f02; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_support_replies_ticket_id_0bc90f02 ON public.public_support_replies USING btree (ticket_id);


--
-- Name: public_support_tickets_ticket_number_e1f088c7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_support_tickets_ticket_number_e1f088c7_like ON public.public_support_tickets USING btree (ticket_number varchar_pattern_ops);


--
-- Name: public_tena_created_200a5e_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tena_created_200a5e_idx ON public.public_tenant_signup_requests USING btree (created_at);


--
-- Name: public_tena_email_de7076_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tena_email_de7076_idx ON public.public_tenant_signup_requests USING btree (email);


--
-- Name: public_tena_status_dcb7f8_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tena_status_dcb7f8_idx ON public.public_tenant_signup_requests USING btree (status);


--
-- Name: public_tena_subdoma_cc0cf0_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tena_subdoma_cc0cf0_idx ON public.public_tenant_signup_requests USING btree (subdomain);


--
-- Name: public_tenant_approval_workflow_reviewed_by_id_0689d809; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tenant_approval_workflow_reviewed_by_id_0689d809 ON public.public_tenant_approval_workflow USING btree (reviewed_by_id);


--
-- Name: public_tenant_notification_log_signup_request_id_d58a838e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tenant_notification_log_signup_request_id_d58a838e ON public.public_tenant_notification_log USING btree (signup_request_id);


--
-- Name: public_tenant_signup_requests_subdomain_ebf310ca_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_tenant_signup_requests_subdomain_ebf310ca_like ON public.public_tenant_signup_requests USING btree (subdomain varchar_pattern_ops);


--
-- Name: public_user_action_3329d1_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_action_3329d1_idx ON public.public_user_activities USING btree (action, "timestamp");


--
-- Name: public_user_activities_user_id_af52c908; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_activities_user_id_af52c908 ON public.public_user_activities USING btree (user_id);


--
-- Name: public_user_email_4d094c_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_email_4d094c_idx ON public.public_users USING btree (email);


--
-- Name: public_user_identif_cc919c_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_identif_cc919c_idx ON public.public_users USING btree (identifier);


--
-- Name: public_user_is_acti_d36014_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_is_acti_d36014_idx ON public.public_users USING btree (is_active, is_staff);


--
-- Name: public_user_user_id_c0976b_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_user_user_id_c0976b_idx ON public.public_user_activities USING btree (user_id, "timestamp");


--
-- Name: public_users_email_7ad3fb5d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_users_email_7ad3fb5d_like ON public.public_users USING btree (email varchar_pattern_ops);


--
-- Name: public_users_identifier_4df4d8df_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_users_identifier_4df4d8df_like ON public.public_users USING btree (identifier varchar_pattern_ops);


--
-- Name: public_users_username_85d526ea_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX public_users_username_85d526ea_like ON public.public_users USING btree (username varchar_pattern_ops);


--
-- Name: tenant_domains_domain_bb1a2d78_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tenant_domains_domain_bb1a2d78_like ON public.tenant_domains USING btree (domain varchar_pattern_ops);


--
-- Name: tenant_domains_tenant_id_6d1ef00b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tenant_domains_tenant_id_6d1ef00b ON public.tenant_domains USING btree (tenant_id);


--
-- Name: tenant_domains_tenant_id_6d1ef00b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tenant_domains_tenant_id_6d1ef00b_like ON public.tenant_domains USING btree (tenant_id varchar_pattern_ops);


--
-- Name: tenant_email_settings_company_id_76056869_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tenant_email_settings_company_id_76056869_like ON public.tenant_email_settings USING btree (company_id varchar_pattern_ops);


--
-- Name: tenant_invoice_settings_company_id_7a293fb7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tenant_invoice_settings_company_id_7a293fb7_like ON public.tenant_invoice_settings USING btree (company_id varchar_pattern_ops);


--
-- Name: company_company company_company_plan_id_2c0e5a90_fk_company_subscriptionplan_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_company
    ADD CONSTRAINT company_company_plan_id_2c0e5a90_fk_company_subscriptionplan_id FOREIGN KEY (plan_id) REFERENCES public.company_subscriptionplan(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: company_companyrelationship company_companyrelat_company_id_9af6d45a_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_companyrelationship
    ADD CONSTRAINT company_companyrelat_company_id_9af6d45a_fk_company_c FOREIGN KEY (company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: company_companyrelationship company_companyrelat_related_company_id_cf18739d_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_companyrelationship
    ADD CONSTRAINT company_companyrelat_related_company_id_cf18739d_fk_company_c FOREIGN KEY (related_company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: company_crosscompanytransaction company_crosscompany_destination_company__54932cef_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_crosscompanytransaction
    ADD CONSTRAINT company_crosscompany_destination_company__54932cef_fk_company_c FOREIGN KEY (destination_company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: company_crosscompanytransaction company_crosscompany_source_company_id_780155ca_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_crosscompanytransaction
    ADD CONSTRAINT company_crosscompany_source_company_id_780155ca_fk_company_c FOREIGN KEY (source_company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_celery_beat_periodictask django_celery_beat_p_clocked_id_47a69f82_fk_django_ce; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_p_clocked_id_47a69f82_fk_django_ce FOREIGN KEY (clocked_id) REFERENCES public.django_celery_beat_clockedschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_celery_beat_periodictask django_celery_beat_p_crontab_id_d3cba168_fk_django_ce; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_p_crontab_id_d3cba168_fk_django_ce FOREIGN KEY (crontab_id) REFERENCES public.django_celery_beat_crontabschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_celery_beat_periodictask django_celery_beat_p_interval_id_a8ca27da_fk_django_ce; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_p_interval_id_a8ca27da_fk_django_ce FOREIGN KEY (interval_id) REFERENCES public.django_celery_beat_intervalschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_celery_beat_periodictask django_celery_beat_p_solar_id_a87ce72c_fk_django_ce; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_celery_beat_periodictask
    ADD CONSTRAINT django_celery_beat_p_solar_id_a87ce72c_fk_django_ce FOREIGN KEY (solar_id) REFERENCES public.django_celery_beat_solarschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: primebooks_appversion primebooks_appversio_rollback_target_id_aad417f8_fk_primebook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_appversion
    ADD CONSTRAINT primebooks_appversio_rollback_target_id_aad417f8_fk_primebook FOREIGN KEY (rollback_target_id) REFERENCES public.primebooks_appversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: primebooks_errorreport primebooks_errorrepo_app_version_id_78838568_fk_primebook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_errorreport
    ADD CONSTRAINT primebooks_errorrepo_app_version_id_78838568_fk_primebook FOREIGN KEY (app_version_id) REFERENCES public.primebooks_appversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: primebooks_maintenancewindow primebooks_maintenan_version_id_92901ac5_fk_primebook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_maintenancewindow
    ADD CONSTRAINT primebooks_maintenan_version_id_92901ac5_fk_primebook FOREIGN KEY (version_id) REFERENCES public.primebooks_appversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: primebooks_updatelog primebooks_updatelog_version_id_7364cf6f_fk_primebook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primebooks_updatelog
    ADD CONSTRAINT primebooks_updatelog_version_id_7364cf6f_fk_primebook FOREIGN KEY (version_id) REFERENCES public.primebooks_appversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_blog_comments public_blog_comments_post_id_a93f78ae_fk_public_blog_posts_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_comments
    ADD CONSTRAINT public_blog_comments_post_id_a93f78ae_fk_public_blog_posts_id FOREIGN KEY (post_id) REFERENCES public.public_blog_posts(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_blog_posts public_blog_posts_category_id_f060c64b_fk_public_bl; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_blog_posts
    ADD CONSTRAINT public_blog_posts_category_id_f060c64b_fk_public_bl FOREIGN KEY (category_id) REFERENCES public.public_blog_categories(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_password_reset_tokens public_password_rese_user_id_4aeb9d7d_fk_public_us; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_password_reset_tokens
    ADD CONSTRAINT public_password_rese_user_id_4aeb9d7d_fk_public_us FOREIGN KEY (user_id) REFERENCES public.public_users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_seo_audits public_seo_audits_page_id_2991d684_fk_public_seo_pages_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_audits
    ADD CONSTRAINT public_seo_audits_page_id_2991d684_fk_public_seo_pages_id FOREIGN KEY (page_id) REFERENCES public.public_seo_pages(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_seo_ranking_history public_seo_ranking_h_keyword_tracking_id_250ed7e6_fk_public_se; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_seo_ranking_history
    ADD CONSTRAINT public_seo_ranking_h_keyword_tracking_id_250ed7e6_fk_public_se FOREIGN KEY (keyword_tracking_id) REFERENCES public.public_seo_keyword_tracking(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_support_replies public_support_repli_ticket_id_0bc90f02_fk_public_su; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_support_replies
    ADD CONSTRAINT public_support_repli_ticket_id_0bc90f02_fk_public_su FOREIGN KEY (ticket_id) REFERENCES public.public_support_tickets(ticket_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_tenant_approval_workflow public_tenant_approv_reviewed_by_id_0689d809_fk_public_us; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_approval_workflow
    ADD CONSTRAINT public_tenant_approv_reviewed_by_id_0689d809_fk_public_us FOREIGN KEY (reviewed_by_id) REFERENCES public.public_users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_tenant_approval_workflow public_tenant_approv_signup_request_id_ac3c96b4_fk_public_te; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_approval_workflow
    ADD CONSTRAINT public_tenant_approv_signup_request_id_ac3c96b4_fk_public_te FOREIGN KEY (signup_request_id) REFERENCES public.public_tenant_signup_requests(request_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_tenant_notification_log public_tenant_notifi_signup_request_id_d58a838e_fk_public_te; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_tenant_notification_log
    ADD CONSTRAINT public_tenant_notifi_signup_request_id_d58a838e_fk_public_te FOREIGN KEY (signup_request_id) REFERENCES public.public_tenant_signup_requests(request_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: public_user_activities public_user_activities_user_id_af52c908_fk_public_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_user_activities
    ADD CONSTRAINT public_user_activities_user_id_af52c908_fk_public_users_id FOREIGN KEY (user_id) REFERENCES public.public_users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: tenant_domains tenant_domains_tenant_id_6d1ef00b_fk_company_company_company_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_tenant_id_6d1ef00b_fk_company_company_company_id FOREIGN KEY (tenant_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: tenant_email_settings tenant_email_setting_company_id_76056869_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_email_settings
    ADD CONSTRAINT tenant_email_setting_company_id_76056869_fk_company_c FOREIGN KEY (company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: tenant_invoice_settings tenant_invoice_setti_company_id_7a293fb7_fk_company_c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invoice_settings
    ADD CONSTRAINT tenant_invoice_setti_company_id_7a293fb7_fk_company_c FOREIGN KEY (company_id) REFERENCES public.company_company(company_id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

\unrestrict ntSPPmpHcdLdAv1BXYA3YGBzwyCiQIYbxvSFl0Pd0XOv5tpvlNROBthaxh77baZ

