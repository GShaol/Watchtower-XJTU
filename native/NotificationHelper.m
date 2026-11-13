#import <Cocoa/Cocoa.h>
#import <UserNotifications/UserNotifications.h>

static NSDictionary *Input;
static void Finish(NSDictionary *result) {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        fwrite(data.bytes,1,data.length,stdout);fwrite("\n",1,1,stdout);fflush(stdout);
        exit([result[@"submitted"] boolValue] || [Input[@"action"] isEqual:@"status"] ? 0 : 1);
    });
}
static NSMutableDictionary *Describe(UNNotificationSettings *s) {
    NSArray *states=@[@"notDetermined",@"denied",@"authorized",@"provisional",@"ephemeral"];
    NSInteger n=s.authorizationStatus;
    return [@{@"authorization":n<states.count?states[n]:@"unknown",@"alertsEnabled":@(s.alertSetting==UNNotificationSettingEnabled),@"centerEnabled":@(s.notificationCenterSetting==UNNotificationSettingEnabled),@"soundEnabled":@(s.soundSetting==UNNotificationSettingEnabled),@"alertStyle":@(s.alertStyle),@"submitted":@NO,@"provider":@"native"} mutableCopy];
}
static void Submit(UNNotificationSettings *s) {
    NSMutableDictionary *result=Describe(s);
    if ([Input[@"action"] isEqual:@"status"]) {Finish(result);return;}
    if (s.authorizationStatus!=UNAuthorizationStatusAuthorized && s.authorizationStatus!=UNAuthorizationStatusProvisional) {
        result[@"error"]=@"Watchtower 通知权限尚未允许";Finish(result);return;
    }
    UNMutableNotificationContent *c=[UNMutableNotificationContent new];
    c.title=Input[@"title"]?:@"Watchtower";
    c.subtitle=Input[@"subtitle"]?:@"";c.body=Input[@"message"]?:@"";
    if ([Input[@"sound"] length]) c.sound=UNNotificationSound.defaultSound;
    c.userInfo=@{@"url":Input[@"url"]?:@"http://127.0.0.1:18767/"};
    UNNotificationRequest *r=[UNNotificationRequest requestWithIdentifier:NSUUID.UUID.UUIDString content:c trigger:[UNTimeIntervalNotificationTrigger triggerWithTimeInterval:1 repeats:NO]];
    [[UNUserNotificationCenter currentNotificationCenter] addNotificationRequest:r withCompletionHandler:^(NSError *error){
        result[@"submitted"]=@(error==nil);
        if(error)result[@"error"]=error.localizedDescription;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC),dispatch_get_main_queue(),^{
            [[UNUserNotificationCenter currentNotificationCenter] getDeliveredNotificationsWithCompletionHandler:^(NSArray<UNNotification *> *notifications){
                BOOL found=NO;for(UNNotification *n in notifications)if([n.request.identifier isEqual:r.identifier]){found=YES;break;}
                result[@"delivered"]=@(found);result[@"deliveredCount"]=@(notifications.count);Finish(result);
            }];
        });
    }];
}
@interface AppDelegate:NSObject<NSApplicationDelegate,UNUserNotificationCenterDelegate>
@end
@implementation AppDelegate
-(void)applicationDidFinishLaunching:(NSNotification *)n {
    UNUserNotificationCenter *center=UNUserNotificationCenter.currentNotificationCenter;center.delegate=self;
    [center getNotificationSettingsWithCompletionHandler:^(UNNotificationSettings *s){
        if (s.authorizationStatus==UNAuthorizationStatusNotDetermined && ![Input[@"action"] isEqual:@"status"]) {
            [center requestAuthorizationWithOptions:UNAuthorizationOptionAlert|UNAuthorizationOptionSound|UNAuthorizationOptionBadge completionHandler:^(BOOL granted,NSError *error){
                [center getNotificationSettingsWithCompletionHandler:^(UNNotificationSettings *after){Submit(after);}];
            }];
        } else Submit(s);
    }];
}
-(void)userNotificationCenter:(UNUserNotificationCenter *)center willPresentNotification:(UNNotification *)n withCompletionHandler:(void(^)(UNNotificationPresentationOptions))done {
    done(UNNotificationPresentationOptionBanner|UNNotificationPresentationOptionList|UNNotificationPresentationOptionSound);
}
-(void)userNotificationCenter:(UNUserNotificationCenter *)center didReceiveNotificationResponse:(UNNotificationResponse *)r withCompletionHandler:(void(^)(void))done {
    NSString *url=r.notification.request.content.userInfo[@"url"];
    if([url hasPrefix:@"http://"]||[url hasPrefix:@"https://"])[NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:url]];
    done();
}
@end
int main(int argc,char **argv) { @autoreleasepool {
    NSApplication *app=NSApplication.sharedApplication;
    [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
    NSData *raw=[NSFileHandle.fileHandleWithStandardInput readDataToEndOfFile];
    id parsed=raw.length?[NSJSONSerialization JSONObjectWithData:raw options:0 error:nil]:nil;
    Input=[parsed isKindOfClass:NSDictionary.class]?parsed:@{@"action":@"status"};
    AppDelegate *delegate=[AppDelegate new];app.delegate=delegate;[app run];
}return 0;}
