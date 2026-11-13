#import <Foundation/Foundation.h>
#import <Security/Security.h>
int main(void) { @autoreleasepool {
 NSDictionary *p=[NSJSONSerialization JSONObjectWithData:[[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile] options:0 error:NULL];
 NSString *service=p[@"service"], *site=p[@"site"], *action=p[@"action"];
 NSMutableDictionary *out=[@{@"ok":@NO} mutableCopy];
 if ([service isKindOfClass:NSString.class] && ([service hasPrefix:@"org.watchtower.community.scholarone."] || [service hasPrefix:@"org.watchtower.community.connection."]) && [site isKindOfClass:NSString.class]) {
  NSMutableDictionary *q=[@{(__bridge id)kSecClass:(__bridge id)kSecClassGenericPassword,(__bridge id)kSecAttrService:service,(__bridge id)kSecAttrAccount:site} mutableCopy];
  OSStatus status=errSecParam;
  if ([action isEqual:@"put"] && [p[@"value"] isKindOfClass:NSDictionary.class]) {
   NSData *data=[NSJSONSerialization dataWithJSONObject:p[@"value"] options:0 error:NULL];
   status=SecItemUpdate((__bridge CFDictionaryRef)q,(__bridge CFDictionaryRef)@{(__bridge id)kSecValueData:data});
   if(status==errSecItemNotFound){q[(__bridge id)kSecValueData]=data;status=SecItemAdd((__bridge CFDictionaryRef)q,NULL);}
  } else if ([action isEqual:@"get"]) {
   q[(__bridge id)kSecReturnData]=@YES;
   CFTypeRef result=NULL;status=SecItemCopyMatching((__bridge CFDictionaryRef)q,&result);
   if(status==errSecSuccess){NSData *data=CFBridgingRelease(result);out[@"value"]=[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL]?:@{};}
  } else if ([action isEqual:@"delete"]) {status=SecItemDelete((__bridge CFDictionaryRef)q);}
  out[@"ok"]=@(status==errSecSuccess);out[@"status"]=@(status);
 }
 NSData *data=[NSJSONSerialization dataWithJSONObject:out options:0 error:NULL];
 [[NSFileHandle fileHandleWithStandardOutput] writeData:data];
} return 0; }
